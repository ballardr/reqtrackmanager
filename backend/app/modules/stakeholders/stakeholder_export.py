"""
Module: modules.stakeholders.stakeholder_export

The Stakeholder half of this module's contribution to the core org/project
bundle export/import (`export.py` holds the Persona half; `module.py` composes
the two into the single `ModuleOrgBundleHooks`/`ModuleProjectBundleHooks`).

- Org level: the Stakeholder type vocabulary and org-scoped stakeholders.
- Project level: project-scoped stakeholders (with direct file attachments)
  and the project's Stakeholder type overrides/local types.
- Stakeholder groups, at both levels: each group is keyed by its
  name path from the root (every element carries its scope, since a project
  group may sit under an org group), with its members by stakeholder name and
  scope. Importing merges into an existing group of the same path and warns
  and skips a group or member it cannot place.

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
from app.modules.stakeholders import groups as grp
from app.modules.stakeholders._principals import STAKEHOLDER_PRINCIPAL_FIELDS, principals_from_bundle, principals_to_bundle
from app.modules.stakeholders.enums import PersonaScope, StakeholderScope, StakeholderStatus, TargetCadence
from app.modules.stakeholders.models import (
    Persona,
    ProjectStakeholderType,
    ProjectStakeholderVisibility,
    Stakeholder,
    StakeholderFile,
    StakeholderGroup,
    StakeholderTypeDefinition,
)
from app.modules.stakeholders.scoring import INFLUENCE_AXIS_KEY, INTEREST_AXIS_KEY, STAKEHOLDER_SCORING_SCHEME_KEY
from app.modules.stakeholders.service import (
    STAKEHOLDER_ARTEFACT_TYPE,
    STAKEHOLDER_TYPES,
    add_represents_link,
    create_stakeholder,
    get_current_persona_version,
    get_current_stakeholder_version,
    list_represented_personas,
)
from app.services.bundle_common import BundleImportWarnings, UserResolver, import_bundled_file
from app.services.tags import record_tag_names, restore_record_tags

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
    # `unique_code` is informational: an import numbers the stakeholder afresh and matches by name.
    data: dict[str, Any] = {"unique_code": stakeholder.unique_code, **{f: getattr(v, f) for f in _TEXT_FIELDS}}
    type_is_local = False
    if v.project_type_id is not None:
        row = db.get(ProjectStakeholderType, v.project_type_id)
        type_is_local = row is not None and row.org_type_id is None
    data.update({
        "type_name": STAKEHOLDER_TYPES.display_name(db, org_type_id=v.org_type_id, project_type_id=v.project_type_id),
        "type_is_project_local": type_is_local, "status": v.status.value,
        "target_cadence": v.target_cadence.value if v.target_cadence else None,
        "influence_level": _level_name(db, v.influence_level_id), "interest_level": _level_name(db, v.interest_level_id),
        **principals_to_bundle(db, v, STAKEHOLDER_PRINCIPAL_FIELDS), "user_email": emails.get(v.user_id),
        "created_by_email": emails.get(stakeholder.creator_id), "is_archived": stakeholder.is_archived,
        "archived_at": _j(stakeholder.archived_at), "created_at": _j(stakeholder.created_at),
        "tags": record_tag_names(db, STAKEHOLDER_ARTEFACT_TYPE, stakeholder.id),
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
        ids |= {v.user_id, s.creator_id}
    return _emails(db, ids)


# --- Groups --------------------------------------------------------------------


def _export_groups(
    db: Session, organization_id: UUID, project_id: UUID | None, scope: StakeholderScope
) -> list[dict[str, Any]]:
    """The groups of `scope` (org groups, or `project_id`'s own), parents before children."""
    universe = grp.load_groups(db, organization_id, project_id)
    entries = []
    for g in universe.values():
        if g.scope != scope:
            continue
        chain = [g, *grp.ancestor_chain(universe, g.id)][::-1]
        names = {}
        for sid in grp.member_ids(db, {g.id}):
            member = db.get(Stakeholder, sid)
            if member is not None:
                names[(get_current_stakeholder_version(db, sid).name, member.scope.value)] = None
        entries.append({
            "path": [{"name": n.name, "scope": n.scope.value} for n in chain],
            "unique_code": g.unique_code, "description": g.description, "exclusive_children": g.exclusive_children, "sort_order": g.sort_order,
            "members": [{"name": n, "scope": sc} for n, sc in sorted(names)],
        })
    return sorted(entries, key=lambda e: (len(e["path"]), [p["name"].lower() for p in e["path"]]))


def _import_groups(
    db: Session, entries: list[dict[str, Any]], organization_id: UUID, project_id: UUID | None,
    stakeholders: dict[tuple[str, str], Stakeholder], warnings: BundleImportWarnings,
) -> None:
    """Recreates exported groups (parents first) and their memberships, merging into a group that
    already exists at the same path."""
    own_scope = StakeholderScope.PROJECT if project_id else StakeholderScope.ORGANIZATION
    universe = grp.load_groups(db, organization_id, project_id)

    def path_of(g: StakeholderGroup) -> tuple:
        return tuple((n.scope.value, n.name.lower()) for n in [*grp.ancestor_chain(universe, g.id)][::-1] + [g])

    by_path = {path_of(g): g for g in universe.values()}
    for entry in entries:
        key = tuple((p["scope"], p["name"].lower()) for p in entry["path"])
        context = f"Stakeholder group {' / '.join(p['name'] for p in entry['path'])!r}"
        group = by_path.get(key)
        if group is None:
            parent = by_path.get(key[:-1]) if len(key) > 1 else None
            if len(key) > 1 and parent is None:
                warnings.add(f"{context}: parent group not found — skipped.")
                continue
            if entry["path"][-1]["scope"] != own_scope.value:
                warnings.add(f"{context}: group not found in this organisation — skipped.")
                continue
            try:
                group = grp.create_group(
                    db, scope=own_scope, organization_id=organization_id, project_id=project_id,
                    name=entry["path"][-1]["name"], description=entry.get("description", ""),
                    parent_group_id=parent.id if parent else None, exclusive_children=False,
                )
            except grp.GroupRuleError as exc:
                warnings.add(f"{context}: {exc} — skipped.")
                continue
            group.sort_order = entry.get("sort_order", group.sort_order)
            universe[group.id] = group
            by_path[key] = group
        if group.scope != own_scope:
            continue  # an existing group of the other tier is only a parent here, never edited
        for m in entry.get("members", []):
            stakeholder = stakeholders.get((m["name"], m["scope"]))
            if stakeholder is None:
                warnings.add(f"{context}: member {m['name']!r} not found — skipped.")
                continue
            try:
                grp.add_member(db, group, stakeholder, universe, organization_id, project_id)
            except grp.GroupRuleError as exc:
                if "already in the group" not in str(exc):
                    warnings.add(f"{context}: member {m['name']!r}: {exc}")
    # Applied last so a bundle that holds a stakeholder in several branches can still restore it.
    for entry in entries:
        key = tuple((p["scope"], p["name"].lower()) for p in entry["path"])
        group = by_path.get(key)
        if group is not None and group.scope == own_scope and entry.get("exclusive_children") and not group.exclusive_children:
            group.exclusive_children = True
            try:
                grp.assert_exclusive_integrity(db, group)
            except grp.GroupRuleError as exc:
                group.exclusive_children = False
                warnings.add(f"Stakeholder group {entry['path'][-1]['name']!r}: not marked exclusive — {exc}")
    db.flush()


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
        "stakeholder_groups": _export_groups(db, org.id, None, StakeholderScope.ORGANIZATION),
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
        **principals_from_bundle(
            db, data, STAKEHOLDER_PRINCIPAL_FIELDS, organization_id=organization_id, project_id=project_id,
            users=users, warnings=warnings, context=context,
        ),
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
    restore_record_tags(
        db, organization_id=organization_id, record_project_id=project_id, actor_id=creator_id,
        artefact_type=STAKEHOLDER_ARTEFACT_TYPE, artefact_id=stakeholder.id, names=data.get("tags"),
    )
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
    org_stakeholders = {
        (get_current_stakeholder_version(db, s.id).name, "organization"): s
        for s in db.scalars(select(Stakeholder).where(
            Stakeholder.organization_id == org.id, Stakeholder.scope == StakeholderScope.ORGANIZATION))
    }
    _import_groups(db, data.get("stakeholder_groups", []), org.id, None, org_stakeholders, warnings)


# --- Project level -----------------------------------------------------------


def export_project_data(db: Session, project: Project) -> tuple[dict[str, Any], dict[UUID, FileAsset]]:
    """Project-scoped stakeholders with their attachments, the project's
    Stakeholder type rows and its visibility overrides of org stakeholders."""
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
    visibility_json = []
    for row in db.scalars(select(ProjectStakeholderVisibility).where(ProjectStakeholderVisibility.project_id == project.id)):
        target = db.get(Stakeholder, row.stakeholder_id)
        if target is not None and target.scope == StakeholderScope.ORGANIZATION:
            visibility_json.append({
                "org_stakeholder_name": get_current_stakeholder_version(db, target.id).name, "hidden": row.hidden,
            })
    return {
        "project_stakeholder_types": types_json,
        "project_stakeholder_hidden_org_types": STAKEHOLDER_TYPES.hidden_names(db, project.id, project.organization_id),
        "project_stakeholders": stakeholders_json,
        "project_stakeholder_visibility": visibility_json,
        "project_stakeholder_groups": _export_groups(db, project.organization_id, project.id, StakeholderScope.PROJECT),
    }, assets


def import_project_data(
    db: Session, project: Project, data: dict[str, Any], file_bytes_by_ref: dict[str, bytes], current_user: User,
    users: UserResolver, warnings: BundleImportWarnings,
) -> None:
    """Recreates the project's type rows, stakeholders (with attachments) and
    visibility overrides. An org type or org stakeholder named in the bundle
    that the target organisation lacks is skipped with a warning. Runs after
    the Persona half."""
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

    org_stakeholder_ids = {
        get_current_stakeholder_version(db, s.id).name: s.id
        for s in db.scalars(select(Stakeholder).where(
            Stakeholder.organization_id == organization_id, Stakeholder.scope == StakeholderScope.ORGANIZATION
        ))
    }
    for v in data.get("project_stakeholder_visibility", []):
        stakeholder_id = org_stakeholder_ids.get(v.get("org_stakeholder_name", ""))
        if stakeholder_id is None:
            warnings.add("A stakeholder visibility override was skipped — its stakeholder was not found in the target organisation.")
            continue
        db.add(ProjectStakeholderVisibility(project_id=project.id, stakeholder_id=stakeholder_id, hidden=v["hidden"]))
    # Hidden last: a stakeholder above may use a type the project hides, which needs its row created first.
    for name in STAKEHOLDER_TYPES.hide_by_names(
        db, project.id, organization_id, data.get("project_stakeholder_hidden_org_types", []),
    ):
        warnings.add(f"Hidden stakeholder type {name!r} skipped — the organisation has no such type.")
    db.flush()

    visible = {
        (get_current_stakeholder_version(db, st.id).name, st.scope.value): st
        for st in db.scalars(select(Stakeholder).where(
            ((Stakeholder.project_id == project.id) & (Stakeholder.scope == StakeholderScope.PROJECT))
            | ((Stakeholder.organization_id == organization_id) & (Stakeholder.scope == StakeholderScope.ORGANIZATION))
        ))
    }
    _import_groups(db, data.get("project_stakeholder_groups", []), organization_id, project.id, visible, warnings)
