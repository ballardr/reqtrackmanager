"""
Module: modules.stakeholders.export

This module's contribution to the core org/project bundle export/import
(`app.services.org_export`/`project_export`), registered through
`ModuleOrgBundleHooks`/`ModuleProjectBundleHooks` on `MODULE_DEFINITION`
rather than those core files importing this module.

- Org level: the Persona type vocabulary and org-scoped personas.
- Project level: project-scoped personas (with their direct file
  attachments), the project's type overrides/local types, and the project's
  weight overrides.

Design decisions:
- A persona travels as its *current* content and status only. Version
  history, comments and comment attachments are not carried: a bundle is a
  migration artefact, and re-importing creates version 1 attributed to the
  importer where the original creator can't be matched.
- Cross-references use portable keys, never database ids: a persona's
  export-scoped `ref`, a type's name, a user's email.
- Org-level files cannot travel: `ModuleOrgBundleHooks.import_` receives no
  attachment bytes, so an org persona's attachments are skipped with a
  warning on export-side documentation rather than silently half-imported.
- Merge into an existing org skips a same-named org persona/type (with a
  warning) so a re-import is idempotent.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.file import FileAsset
from app.models.organization import Organization
from app.models.project import Project
from app.models.user import User
from app.modules.stakeholders.enums import PersonaScope, PersonaStatus
from app.modules.stakeholders.models import (
    Persona,
    PersonaFile,
    PersonaTypeDefinition,
    ProjectPersonaType,
    ProjectPersonaWeight,
)
from app.modules.stakeholders.service import (
    PERSONA_TYPES,
    create_persona,
    get_current_persona_version,
)
from app.services.bundle_common import BundleImportWarnings, UserResolver, import_bundled_file

_TEXT_FIELDS = (
    "name", "description", "role_title", "goals", "needs", "behaviours", "context_environment",
    "skills_proficiency", "frequency_of_use", "constraints", "weight",
)


def _j(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _emails(db: Session, user_ids: set[UUID | None]) -> dict[UUID, str]:
    ids = {u for u in user_ids if u is not None}
    return {u.id: u.email for u in db.scalars(select(User).where(User.id.in_(ids)))} if ids else {}


def _persona_json(db: Session, persona: Persona, ref: str, emails: dict[UUID, str]) -> dict[str, Any]:
    v = get_current_persona_version(db, persona.id)
    data: dict[str, Any] = {"ref": ref, **{f: getattr(v, f) for f in _TEXT_FIELDS}}
    type_name = PERSONA_TYPES.display_name(db, org_type_id=v.org_type_id, project_type_id=v.project_type_id)
    type_is_local = False
    if v.project_type_id is not None:
        row = db.get(ProjectPersonaType, v.project_type_id)
        type_is_local = row is not None and row.org_type_id is None
    data.update({
        "type_name": type_name, "type_is_project_local": type_is_local, "status": v.status.value,
        "owner_email": emails.get(v.owner_id), "champion_email": emails.get(v.champion_id),
        "created_by_email": emails.get(persona.creator_id), "is_archived": persona.is_archived,
        "archived_at": _j(persona.archived_at), "created_at": _j(persona.created_at),
    })
    return data


def _persona_emails(db: Session, personas: list[Persona]) -> dict[UUID, str]:
    ids: set[UUID | None] = set()
    for p in personas:
        v = get_current_persona_version(db, p.id)
        ids |= {v.owner_id, v.champion_id, p.creator_id}
    return _emails(db, ids)


# --- Org level ---------------------------------------------------------------


def export_org_data(db: Session, org: Organization) -> dict[str, Any]:
    """`ModuleOrgBundleHooks.export`: the org's Persona types and org-scoped
    personas (archived included — a bundle is a backup, readers filter)."""
    types = db.scalars(
        select(PersonaTypeDefinition).where(PersonaTypeDefinition.organization_id == org.id)
        .order_by(PersonaTypeDefinition.sort_order)
    ).all()
    personas = list(db.scalars(
        select(Persona).where(Persona.organization_id == org.id, Persona.scope == PersonaScope.ORGANIZATION)
        .order_by(Persona.created_at)
    ).all())
    emails = _persona_emails(db, personas)
    return {
        "persona_types": [{"name": t.name, "sort_order": t.sort_order, "is_active": t.is_active} for t in types],
        "personas": [_persona_json(db, p, f"PERSONA-{i + 1}", emails) for i, p in enumerate(personas)],
    }


def _create_persona_from_json(
    db: Session, data: dict[str, Any], *, scope: PersonaScope, organization_id: UUID, project_id: UUID | None,
    org_type_id: UUID | None, project_type_id: UUID | None, users: UserResolver,
) -> Persona:
    creator_id = users.resolve(data.get("created_by_email"), required=True, context=f"Persona {data['name']!r} creator")
    creator = db.get(User, creator_id)
    persona = create_persona(
        db, scope=scope, organization_id=organization_id, project_id=project_id, creator=creator,
        org_type_id=org_type_id, project_type_id=project_type_id,
        owner_id=users.resolve(data.get("owner_email"), required=False, context=f"Persona {data['name']!r} owner"),
        champion_id=users.resolve(data.get("champion_email"), required=False, context=f"Persona {data['name']!r} champion"),
        **{f: data.get(f, "" if f != "weight" else None) for f in _TEXT_FIELDS},
    )
    version = get_current_persona_version(db, persona.id)
    version.status = PersonaStatus(data.get("status", "draft"))
    version.change_note = "Imported from bundle."
    persona.is_archived = bool(data.get("is_archived"))
    persona.archived_at = _dt(data.get("archived_at"))
    persona.archived_by = creator_id if persona.is_archived else None
    return persona


def import_org_data(
    db: Session, org: Organization, data: dict[str, Any], users: UserResolver, warnings: BundleImportWarnings,
    resolutions: dict[str, str] | None,
) -> None:
    """`ModuleOrgBundleHooks.import_`: recreates Persona types (skipping names
    the org already has) and org personas (skipping same-named ones)."""
    existing_types = {t.name: t for t in db.scalars(select(PersonaTypeDefinition).where(PersonaTypeDefinition.organization_id == org.id))}
    for t in data.get("persona_types", []):
        if t["name"] in existing_types:
            continue
        row = PersonaTypeDefinition(
            organization_id=org.id, name=t["name"], sort_order=t.get("sort_order", len(existing_types)),
            is_active=t.get("is_active", True),
        )
        db.add(row)
        existing_types[t["name"]] = row
    db.flush()

    existing_names = {
        get_current_persona_version(db, p.id).name
        for p in db.scalars(select(Persona).where(Persona.organization_id == org.id, Persona.scope == PersonaScope.ORGANIZATION))
    }
    for p in data.get("personas", []):
        if p["name"] in existing_names:
            warnings.add(f"Persona {p['name']!r} already exists in this organisation — skipped.")
            continue
        type_row = existing_types.get(p.get("type_name") or "")
        if p.get("type_name") and type_row is None:
            warnings.add(f"Persona {p['name']!r}: type {p['type_name']!r} not found — left untyped.")
        _create_persona_from_json(
            db, p, scope=PersonaScope.ORGANIZATION, organization_id=org.id, project_id=None,
            org_type_id=type_row.id if type_row else None, project_type_id=None, users=users,
        )
    db.flush()


# --- Project level -----------------------------------------------------------


def export_project_data(db: Session, project: Project) -> tuple[dict[str, Any], dict[UUID, FileAsset]]:
    """`ModuleProjectBundleHooks.export`: project-scoped personas with their
    attachments, the project's type rows and its weight overrides (which may
    target an org persona, recorded by that persona's name)."""
    assets: dict[UUID, FileAsset] = {}
    personas = list(db.scalars(
        select(Persona).where(Persona.project_id == project.id, Persona.scope == PersonaScope.PROJECT).order_by(Persona.created_at)
    ).all())
    emails = _persona_emails(db, personas)
    personas_json = []
    for i, persona in enumerate(personas):
        entry = _persona_json(db, persona, f"PROJECT-PERSONA-{i + 1}", emails)
        attachments = []
        for asset, linked_by in db.execute(
            select(FileAsset, User).join(PersonaFile, PersonaFile.file_id == FileAsset.id)
            .join(User, User.id == PersonaFile.linked_by).where(PersonaFile.persona_id == persona.id)
        ).all():
            assets[asset.id] = asset
            attachments.append({
                "file_ref": f"{asset.id}_{asset.filename}", "filename": asset.filename,
                "content_type": asset.content_type, "linked_by_email": linked_by.email,
            })
        entry["attachments"] = attachments
        personas_json.append(entry)

    types_json = []
    for row in db.scalars(select(ProjectPersonaType).where(ProjectPersonaType.project_id == project.id)):
        org_type = db.get(PersonaTypeDefinition, row.org_type_id) if row.org_type_id else None
        types_json.append({
            "org_type_name": org_type.name if org_type else None, "name_override": row.name_override,
            "display_order_override": row.display_order_override, "is_enabled": row.is_enabled,
        })

    ref_by_id = {p.id: f"PROJECT-PERSONA-{i + 1}" for i, p in enumerate(personas)}
    weights_json = []
    for w in db.scalars(select(ProjectPersonaWeight).where(ProjectPersonaWeight.project_id == project.id)):
        if w.persona_id in ref_by_id:
            weights_json.append({"persona_ref": ref_by_id[w.persona_id], "weight": w.weight})
        else:
            target = db.get(Persona, w.persona_id)
            if target is not None and target.scope == PersonaScope.ORGANIZATION:
                weights_json.append({"org_persona_name": get_current_persona_version(db, target.id).name, "weight": w.weight})
    return {"project_persona_types": types_json, "project_personas": personas_json, "project_persona_weights": weights_json}, assets


def import_project_data(
    db: Session, project: Project, data: dict[str, Any], file_bytes_by_ref: dict[str, bytes], current_user: User,
    users: UserResolver, warnings: BundleImportWarnings,
) -> None:
    """`ModuleProjectBundleHooks.import_`: recreates the project's type rows,
    personas (with attachments) and weight overrides. An org type or org
    persona named in the bundle that the target organisation lacks is skipped
    with a warning."""
    organization_id = project.organization_id
    org_types = {t.name: t for t in db.scalars(select(PersonaTypeDefinition).where(PersonaTypeDefinition.organization_id == organization_id))}
    local_types: dict[str, ProjectPersonaType] = {}
    for t in data.get("project_persona_types", []):
        if t.get("org_type_name"):
            org_type = org_types.get(t["org_type_name"])
            if org_type is None:
                warnings.add(f"Persona type override for {t['org_type_name']!r} skipped — the organisation has no such type.")
                continue
            row = PERSONA_TYPES.get_or_create_project_type(db, project.id, organization_id, org_type.id)
            PERSONA_TYPES.set_override(
                db, row, name=t.get("name_override"), display_order=t.get("display_order_override"), is_enabled=t.get("is_enabled"),
            )
        else:
            row = PERSONA_TYPES.create_project_local(
                db, project.id, t["name_override"], display_order=t.get("display_order_override"),
            )
            row.is_enabled = t.get("is_enabled", True)
            local_types[t["name_override"]] = row

    persona_id_by_ref: dict[str, UUID] = {}
    for p in data.get("project_personas", []):
        project_type_id = None
        if p.get("type_name"):
            if p.get("type_is_project_local"):
                row = local_types.get(p["type_name"])
            else:
                org_type = next((t for t in org_types.values() if t.name == p["type_name"]), None)
                row = (
                    PERSONA_TYPES.get_or_create_project_type(db, project.id, organization_id, org_type.id)
                    if org_type else _find_renamed_override(db, project.id, p["type_name"])
                )
            if row is None:
                warnings.add(f"Persona {p['name']!r}: type {p['type_name']!r} not found — left untyped.")
            else:
                project_type_id = row.id
        persona = _create_persona_from_json(
            db, p, scope=PersonaScope.PROJECT, organization_id=organization_id, project_id=project.id,
            org_type_id=None, project_type_id=project_type_id, users=users,
        )
        persona_id_by_ref[p["ref"]] = persona.id
        for att in p.get("attachments", []):
            att_bytes = file_bytes_by_ref.get(att["file_ref"])
            if att_bytes is None:
                continue
            uploader_id = users.resolve(att.get("linked_by_email"), required=False, context="Persona attachment uploader") or current_user.id
            asset = import_bundled_file(
                db, organization_id=organization_id, uploaded_by=uploader_id, filename=att["filename"],
                content_type=att.get("content_type") or "application/octet-stream", data=att_bytes,
            )
            db.add(PersonaFile(persona_id=persona.id, file_id=asset.id, linked_by=uploader_id, created_at=datetime.now(UTC)))
    db.flush()

    org_persona_ids = {
        get_current_persona_version(db, persona.id).name: persona.id
        for persona in db.scalars(select(Persona).where(Persona.organization_id == organization_id, Persona.scope == PersonaScope.ORGANIZATION))
    }
    for w in data.get("project_persona_weights", []):
        persona_id = persona_id_by_ref.get(w.get("persona_ref", "")) or org_persona_ids.get(w.get("org_persona_name", ""))
        if persona_id is None:
            warnings.add("A persona weight override was skipped — its persona was not found in the target organisation.")
            continue
        db.add(ProjectPersonaWeight(project_id=project.id, persona_id=persona_id, weight=w["weight"]))
    db.flush()


def _find_renamed_override(db: Session, project_id: UUID, name: str) -> ProjectPersonaType | None:
    """The project's own type row whose effective name is `name` (a renamed
    org type whose org original no longer matches by name)."""
    return db.scalar(select(ProjectPersonaType).where(ProjectPersonaType.project_id == project_id, ProjectPersonaType.name_override == name))
