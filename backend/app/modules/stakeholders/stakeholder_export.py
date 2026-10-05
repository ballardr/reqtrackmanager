"""
Module: modules.stakeholders.stakeholder_export

The Stakeholder half of this module's contribution to the core org/project
bundle export/import (`export.py` holds the Persona half; `module.py` composes
the two into the single `ModuleOrgBundleHooks`/`ModuleProjectBundleHooks`).

- Org level: the Stakeholder type vocabulary and org-scoped stakeholders.
- Project level: project-scoped stakeholders (with direct file attachments)
  and the project's Stakeholder type overrides/local types.

Design decisions:
- Same carry-over rules as the Persona bundle: current content and status
  only, no version history, comments or comment attachments; cross-references
  use portable keys (a type's name, a user's email, a scoring level's name, a
  persona's name and scope), never database ids; org-level files cannot travel;
  merging into an existing org skips a same-named stakeholder/type.
- A bundle holds Confidential personal data (contact info, names). It is an
  explicit operator-initiated backup and sits under the same handling rules as
  any other export (data classification policy); nothing here widens who can
  read it.
- "Represents" links are exported by persona name and resolved after the
  Persona half has imported, so `module.py` always runs that half first. A
  persona the target lacks is skipped with a warning.
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
from app.models.scoring import ScoringLevel
from app.models.user import User
from app.modules.stakeholders.enums import PersonaScope, StakeholderScope, StakeholderStatus, TargetCadence
from app.modules.stakeholders.models import (
    Persona,
    ProjectStakeholderType,
    Stakeholder,
    StakeholderFile,
    StakeholderTypeDefinition,
)
from app.modules.stakeholders.scoring import INFLUENCE_AXIS_KEY, INTEREST_AXIS_KEY, STAKEHOLDER_SCORING_SCHEME_KEY
from app.modules.stakeholders.service import (
    STAKEHOLDER_TYPES,
    add_represents_link,
    create_stakeholder,
    get_current_persona_version,
    get_current_stakeholder_version,
    list_represented_personas,
)
from app.services.bundle_common import BundleImportWarnings, UserResolver, import_bundled_file

_TEXT_FIELDS = (
    "name", "description", "role", "organisation_group", "interests", "responsibilities", "goals_needs",
    "priorities", "constraints", "workflows_scenarios", "contact_info", "availability_constraints",
)


def _j(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _emails(db: Session, user_ids: set[UUID | None]) -> dict[UUID, str]:
    ids = {u for u in user_ids if u is not None}
    return {u.id: u.email for u in db.scalars(select(User).where(User.id.in_(ids)))} if ids else {}


def _level_name(db: Session, level_id: UUID | None) -> str | None:
    level = db.get(ScoringLevel, level_id) if level_id else None
    return level.name if level else None


def _level_by_name(db: Session, organization_id: UUID, axis_key: str, name: str | None) -> ScoringLevel | None:
    if not name:
        return None
    return db.scalar(select(ScoringLevel).where(
        ScoringLevel.organization_id == organization_id, ScoringLevel.scheme_key == STAKEHOLDER_SCORING_SCHEME_KEY,
        ScoringLevel.axis_key == axis_key, ScoringLevel.name == name,
    ))


def _stakeholder_json(db: Session, stakeholder: Stakeholder, organization_id: UUID, emails: dict[UUID, str]) -> dict[str, Any]:
    v = get_current_stakeholder_version(db, stakeholder.id)
    data: dict[str, Any] = {f: getattr(v, f) for f in _TEXT_FIELDS}
    type_is_local = False
    if v.project_type_id is not None:
        row = db.get(ProjectStakeholderType, v.project_type_id)
        type_is_local = row is not None and row.org_type_id is None
    data.update({
        "type_name": STAKEHOLDER_TYPES.display_name(db, org_type_id=v.org_type_id, project_type_id=v.project_type_id),
        "type_is_project_local": type_is_local, "status": v.status.value,
        "target_cadence": v.target_cadence.value if v.target_cadence else None,
        "influence_level": _level_name(db, v.influence_level_id), "interest_level": _level_name(db, v.interest_level_id),
        "owner_email": emails.get(v.owner_id), "user_email": emails.get(v.user_id),
        "created_by_email": emails.get(stakeholder.creator_id), "is_archived": stakeholder.is_archived,
        "archived_at": _j(stakeholder.archived_at), "created_at": _j(stakeholder.created_at),
        "represents": [
            {"persona_name": get_current_persona_version(db, p.id).name, "persona_scope": p.scope.value}
            for _, p in list_represented_personas(db, stakeholder, organization_id)
        ],
    })
    return data


def _stakeholder_emails(db: Session, stakeholders: list[Stakeholder]) -> dict[UUID, str]:
    ids: set[UUID | None] = set()
    for s in stakeholders:
        v = get_current_stakeholder_version(db, s.id)
        ids |= {v.owner_id, v.user_id, s.creator_id}
    return _emails(db, ids)


# --- Org level ---------------------------------------------------------------


def export_org_data(db: Session, org: Organization) -> dict[str, Any]:
    """The org's Stakeholder types and org-scoped stakeholders (archived
    included — a bundle is a backup, readers filter)."""
    types = db.scalars(
        select(StakeholderTypeDefinition).where(StakeholderTypeDefinition.organization_id == org.id)
        .order_by(StakeholderTypeDefinition.sort_order)
    ).all()
    stakeholders = list(db.scalars(
        select(Stakeholder).where(Stakeholder.organization_id == org.id, Stakeholder.scope == StakeholderScope.ORGANIZATION)
        .order_by(Stakeholder.created_at)
    ).all())
    emails = _stakeholder_emails(db, stakeholders)
    return {
        "stakeholder_types": [{"name": t.name, "sort_order": t.sort_order, "is_active": t.is_active} for t in types],
        "stakeholders": [_stakeholder_json(db, s, org.id, emails) for s in stakeholders],
    }


def _persona_ids_by_name(db: Session, organization_id: UUID, project_id: UUID | None) -> dict[tuple[str, str], UUID]:
    """`(name, scope)` -> id for the personas an org/project stakeholder may represent."""
    query = select(Persona).where(
        (Persona.organization_id == organization_id) & (Persona.scope == PersonaScope.ORGANIZATION)
        if project_id is None
        else ((Persona.organization_id == organization_id) & (Persona.scope == PersonaScope.ORGANIZATION))
        | ((Persona.project_id == project_id) & (Persona.scope == PersonaScope.PROJECT))
    )
    return {(get_current_persona_version(db, p.id).name, p.scope.value): p.id for p in db.scalars(query)}


def _create_stakeholder_from_json(
    db: Session, data: dict[str, Any], *, scope: StakeholderScope, organization_id: UUID, project_id: UUID | None,
    org_type_id: UUID | None, project_type_id: UUID | None, users: UserResolver, warnings: BundleImportWarnings,
    personas: dict[tuple[str, str], UUID], current_user: User | None,
) -> Stakeholder:
    context = f"Stakeholder {data['name']!r}"
    creator_id = users.resolve(data.get("created_by_email"), required=True, context=f"{context} creator")
    creator = db.get(User, creator_id)
    influence = _level_by_name(db, organization_id, INFLUENCE_AXIS_KEY, data.get("influence_level"))
    interest = _level_by_name(db, organization_id, INTEREST_AXIS_KEY, data.get("interest_level"))
    for label, wanted, found in (("influence", data.get("influence_level"), influence), ("interest", data.get("interest_level"), interest)):
        if wanted and found is None:
            warnings.add(f"{context}: {label} level {wanted!r} not found — left unscored.")
    stakeholder = create_stakeholder(
        db, scope=scope, organization_id=organization_id, project_id=project_id, creator=creator,
        org_type_id=org_type_id, project_type_id=project_type_id,
        owner_id=users.resolve(data.get("owner_email"), required=False, context=f"{context} owner"),
        user_id=users.resolve(data.get("user_email"), required=False, context=f"{context} user"),
        target_cadence=TargetCadence(data["target_cadence"]) if data.get("target_cadence") else None,
        influence_level_id=influence.id if influence else None, interest_level_id=interest.id if interest else None,
        **{f: data.get(f, "") for f in _TEXT_FIELDS},
    )
    version = get_current_stakeholder_version(db, stakeholder.id)
    version.status = StakeholderStatus(data.get("status", "draft"))
    version.change_note = "Imported from bundle."
    stakeholder.is_archived = bool(data.get("is_archived"))
    stakeholder.archived_at = _dt(data.get("archived_at"))
    stakeholder.archived_by = creator_id if stakeholder.is_archived else None
    db.flush()
    for rep in data.get("represents", []):
        persona_id = personas.get((rep["persona_name"], rep["persona_scope"]))
        persona = db.get(Persona, persona_id) if persona_id else None
        if persona is None:
            warnings.add(f"{context}: represented Persona {rep['persona_name']!r} not found — link skipped.")
            continue
        try:
            add_represents_link(db, stakeholder, persona, current_user or creator, organization_id=organization_id)
        except ValueError as exc:
            warnings.add(f"{context}: {exc}")
    return stakeholder


def import_org_data(
    db: Session, org: Organization, data: dict[str, Any], users: UserResolver, warnings: BundleImportWarnings,
    resolutions: dict[str, str] | None,
) -> None:
    """Recreates Stakeholder types (skipping names the org already has) and
    org stakeholders (skipping same-named ones). Runs after the Persona half."""
    existing_types = {
        t.name: t for t in db.scalars(select(StakeholderTypeDefinition).where(StakeholderTypeDefinition.organization_id == org.id))
    }
    for t in data.get("stakeholder_types", []):
        if t["name"] in existing_types:
            continue
        row = StakeholderTypeDefinition(
            organization_id=org.id, name=t["name"], sort_order=t.get("sort_order", len(existing_types)),
            is_active=t.get("is_active", True),
        )
        db.add(row)
        existing_types[t["name"]] = row
    db.flush()

    existing_names = {
        get_current_stakeholder_version(db, s.id).name
        for s in db.scalars(select(Stakeholder).where(Stakeholder.organization_id == org.id, Stakeholder.scope == StakeholderScope.ORGANIZATION))
    }
    personas = _persona_ids_by_name(db, org.id, None)
    for s in data.get("stakeholders", []):
        if s["name"] in existing_names:
            warnings.add(f"Stakeholder {s['name']!r} already exists in this organisation — skipped.")
            continue
        type_row = existing_types.get(s.get("type_name") or "")
        if s.get("type_name") and type_row is None:
            warnings.add(f"Stakeholder {s['name']!r}: type {s['type_name']!r} not found — left untyped.")
        _create_stakeholder_from_json(
            db, s, scope=StakeholderScope.ORGANIZATION, organization_id=org.id, project_id=None,
            org_type_id=type_row.id if type_row else None, project_type_id=None, users=users, warnings=warnings,
            personas=personas, current_user=None,
        )
    db.flush()


# --- Project level -----------------------------------------------------------


def export_project_data(db: Session, project: Project) -> tuple[dict[str, Any], dict[UUID, FileAsset]]:
    """Project-scoped stakeholders with their attachments and the project's
    Stakeholder type rows."""
    assets: dict[UUID, FileAsset] = {}
    stakeholders = list(db.scalars(
        select(Stakeholder).where(Stakeholder.project_id == project.id, Stakeholder.scope == StakeholderScope.PROJECT)
        .order_by(Stakeholder.created_at)
    ).all())
    emails = _stakeholder_emails(db, stakeholders)
    stakeholders_json = []
    for stakeholder in stakeholders:
        entry = _stakeholder_json(db, stakeholder, project.organization_id, emails)
        attachments = []
        for asset, linked_by in db.execute(
            select(FileAsset, User).join(StakeholderFile, StakeholderFile.file_id == FileAsset.id)
            .join(User, User.id == StakeholderFile.linked_by).where(StakeholderFile.stakeholder_id == stakeholder.id)
        ).all():
            assets[asset.id] = asset
            attachments.append({
                "file_ref": f"{asset.id}_{asset.filename}", "filename": asset.filename,
                "content_type": asset.content_type, "linked_by_email": linked_by.email,
            })
        entry["attachments"] = attachments
        stakeholders_json.append(entry)

    types_json = []
    for row in db.scalars(select(ProjectStakeholderType).where(ProjectStakeholderType.project_id == project.id)):
        org_type = db.get(StakeholderTypeDefinition, row.org_type_id) if row.org_type_id else None
        types_json.append({
            "org_type_name": org_type.name if org_type else None, "name_override": row.name_override,
            "display_order_override": row.display_order_override, "is_enabled": row.is_enabled,
        })
    return {"project_stakeholder_types": types_json, "project_stakeholders": stakeholders_json}, assets


def import_project_data(
    db: Session, project: Project, data: dict[str, Any], file_bytes_by_ref: dict[str, bytes], current_user: User,
    users: UserResolver, warnings: BundleImportWarnings,
) -> None:
    """Recreates the project's type rows and stakeholders (with attachments).
    An org type named in the bundle that the target organisation lacks is
    skipped with a warning. Runs after the Persona half."""
    organization_id = project.organization_id
    org_types = {
        t.name: t for t in db.scalars(select(StakeholderTypeDefinition).where(StakeholderTypeDefinition.organization_id == organization_id))
    }
    local_types: dict[str, ProjectStakeholderType] = {}
    for t in data.get("project_stakeholder_types", []):
        if t.get("org_type_name"):
            org_type = org_types.get(t["org_type_name"])
            if org_type is None:
                warnings.add(f"Stakeholder type override for {t['org_type_name']!r} skipped — the organisation has no such type.")
                continue
            row = STAKEHOLDER_TYPES.get_or_create_project_type(db, project.id, organization_id, org_type.id)
            STAKEHOLDER_TYPES.set_override(
                db, row, name=t.get("name_override"), display_order=t.get("display_order_override"), is_enabled=t.get("is_enabled"),
            )
        else:
            row = STAKEHOLDER_TYPES.create_project_local(
                db, project.id, t["name_override"], display_order=t.get("display_order_override"),
            )
            row.is_enabled = t.get("is_enabled", True)
            local_types[t["name_override"]] = row

    personas = _persona_ids_by_name(db, organization_id, project.id)
    for s in data.get("project_stakeholders", []):
        project_type_id = None
        if s.get("type_name"):
            if s.get("type_is_project_local"):
                row = local_types.get(s["type_name"])
            else:
                org_type = org_types.get(s["type_name"])
                row = (
                    STAKEHOLDER_TYPES.get_or_create_project_type(db, project.id, organization_id, org_type.id)
                    if org_type else db.scalar(select(ProjectStakeholderType).where(
                        ProjectStakeholderType.project_id == project.id, ProjectStakeholderType.name_override == s["type_name"],
                    ))
                )
            if row is None:
                warnings.add(f"Stakeholder {s['name']!r}: type {s['type_name']!r} not found — left untyped.")
            else:
                project_type_id = row.id
        stakeholder = _create_stakeholder_from_json(
            db, s, scope=StakeholderScope.PROJECT, organization_id=organization_id, project_id=project.id,
            org_type_id=None, project_type_id=project_type_id, users=users, warnings=warnings, personas=personas,
            current_user=current_user,
        )
        for att in s.get("attachments", []):
            att_bytes = file_bytes_by_ref.get(att["file_ref"])
            if att_bytes is None:
                continue
            uploader_id = users.resolve(att.get("linked_by_email"), required=False, context="Stakeholder attachment uploader") or current_user.id
            asset = import_bundled_file(
                db, organization_id=organization_id, uploaded_by=uploader_id, filename=att["filename"],
                content_type=att.get("content_type") or "application/octet-stream", data=att_bytes,
            )
            db.add(StakeholderFile(stakeholder_id=stakeholder.id, file_id=asset.id, linked_by=uploader_id, created_at=datetime.now(UTC)))
    db.flush()
