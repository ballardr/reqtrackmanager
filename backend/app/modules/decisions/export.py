"""
Module: modules.decisions.export

This module's contribution to the core org/project bundle export/import
(`app.services.org_export`/`project_export`), registered through
`ModuleOrgBundleHooks`/`ModuleProjectBundleHooks` on `MODULE_DEFINITION` rather
than those core files importing this module.

- Org level: the Decision templates.
- Project level: the project's own Decision types, its Decisions (with
  attachments) and the links between Decisions and to Requirements.

Design decisions (all Decided by: Agent):
- A Decision has no version table, so it travels as it is: content, status,
  decision maker, owner and decision date. Comments and comment attachments are
  not carried (a bundle is a migration artefact, as for the other modules).
- Status is imported as exported, as the core Requirement and Risk sections do:
  the bundle is a restore and importing a project is itself privileged. A
  superseded Decision keeps its status and its "Supersedes" link; replaying the
  link does not run the status transition again.
- A Decision's type travels by name. Types are project-scoped and a child project
  may inherit its ancestor's, so a type the bundle's own list lacks is created in
  the new project with the same name, in a stable order after the exported ones.
  An imported project is a root, so its own types are exactly those the bundle names.
- Codes are information only: an import numbers Decisions afresh in their original
  order, and addresses them inside the bundle by their exported code (`ref`).
- Owner and decision maker are principals (`{type, email | name}`); one the target
  cannot match falls back to the importer (owner) or is left unset (decision maker),
  with a warning.
- Links travel only between this project's Decisions and Requirements
  (`services.bundle_links`); a link to another module's record is that module's.
- Organisation-level files cannot travel; templates have none.

Dependencies: `app.services.bundle_common`, `app.services.bundle_links`,
`app.services.principals`, `app.services.tags`, this module's models and service.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.file import FileAsset
from app.models.organization import Organization
from app.models.project import Project
from app.models.user import User
from app.modules.decisions.enums import DecisionStatus
from app.modules.decisions.models import Decision, DecisionFile, DecisionTemplateDefinition, DecisionTypeDefinition
from app.modules.decisions.service import DECISION_ARTEFACT_TYPE
from app.services.bundle_common import BundleImportWarnings, UserResolver, export_file_links, import_file_links
from app.services.bundle_links import export_artefact_links, import_artefact_links
from app.services.principals import principal_columns_from_bundle, principal_to_bundle
from app.services.sequences import generate_unique_code
from app.services.tags import record_tag_names, restore_record_tags

DECISION_CODE_PREFIX = "DEC"
_TEXT_FIELDS = ("context", "options_considered", "chosen_option", "rationale", "consequences", "assumptions", "constraints")
_TEMPLATE_FIELDS = (
    "description", "context_prompt", "options_considered_prompt", "chosen_option_prompt", "rationale_prompt",
    "consequences_prompt", "assumptions_prompt", "constraints_prompt",
)
_LINKS_KEY = "decision_links"


def _j(value: datetime | date | None) -> str | None:
    """ISO 8601 text for a date or instant, or None."""
    return value.isoformat() if value else None


def _dt(value: str | None) -> datetime | None:
    """Parses an exported instant, or None."""
    return datetime.fromisoformat(value) if value else None


def _date(value: str | None) -> date | None:
    """Parses an exported plain date, or None."""
    return date.fromisoformat(value) if value else None


# --- Org level ---------------------------------------------------------------


def export_org_data(db: Session, org: Organization) -> dict[str, Any]:
    """`ModuleOrgBundleHooks.export`: the organisation's Decision templates."""
    templates = db.scalars(
        select(DecisionTemplateDefinition).where(DecisionTemplateDefinition.organization_id == org.id)
        .order_by(DecisionTemplateDefinition.sort_order)
    ).all()
    return {
        "decision_templates": [
            {"name": t.name, "sort_order": t.sort_order, **{f: getattr(t, f) for f in _TEMPLATE_FIELDS}} for t in templates
        ],
    }


def import_org_data(
    db: Session, org: Organization, data: dict[str, Any], users: UserResolver, warnings: BundleImportWarnings,
    resolutions: dict[str, str] | None,
) -> None:
    """`ModuleOrgBundleHooks.import_`: recreates Decision templates, skipping a name the
    organisation already has (so a template seeded at creation is not doubled)."""
    existing = {t.name for t in db.scalars(select(DecisionTemplateDefinition).where(DecisionTemplateDefinition.organization_id == org.id))}
    for t in data.get("decision_templates", []):
        if t["name"] in existing:
            continue
        db.add(DecisionTemplateDefinition(
            organization_id=org.id, name=t["name"], sort_order=t.get("sort_order", len(existing)),
            **{f: t.get(f) for f in _TEMPLATE_FIELDS},
        ))
        existing.add(t["name"])
    db.flush()


# --- Project level -----------------------------------------------------------


def export_project_data(db: Session, project: Project) -> tuple[dict[str, Any], dict[uuid.UUID, FileAsset]]:
    """`ModuleProjectBundleHooks.export`: the project's own Decision types, its Decisions
    with attachments (archived included — a bundle is a backup) and their links."""
    assets: dict[uuid.UUID, FileAsset] = {}
    own_types = db.scalars(
        select(DecisionTypeDefinition).where(DecisionTypeDefinition.project_id == project.id)
        .order_by(DecisionTypeDefinition.sort_order)
    ).all()
    decisions = list(db.scalars(select(Decision).where(Decision.project_id == project.id).order_by(Decision.unique_code)))
    type_names = {t.id: t.name for t in db.scalars(select(DecisionTypeDefinition).where(
        DecisionTypeDefinition.id.in_({d.decision_type_id for d in decisions})
    ))} if decisions else {}
    user_ids = {d.creator_id for d in decisions} | {d.archived_by for d in decisions}
    emails = {u.id: u.email for u in db.scalars(select(User).where(User.id.in_({u for u in user_ids if u})))} if decisions else {}
    entries = [
        {
            "ref": d.unique_code, "title": d.title, "decision_statement": d.decision_statement,
            "type_name": type_names.get(d.decision_type_id), "status": d.status.value,
            "decision_date": _j(d.decision_date), "decision_maker": principal_to_bundle(db, d.decision_maker_type, d.decision_maker_id),
            "owner": principal_to_bundle(db, d.owner_type, d.owner_id), **{f: getattr(d, f) for f in _TEXT_FIELDS},
            "created_by_email": emails.get(d.creator_id), "created_at": _j(d.created_at), "is_archived": d.is_archived,
            "archived_at": _j(d.archived_at), "archived_by_email": emails.get(d.archived_by),
            "tags": record_tag_names(db, DECISION_ARTEFACT_TYPE, d.id),
            "attachments": export_file_links(db, DecisionFile, "decision_id", d.id, assets),
        }
        for d in decisions
    ]
    return {
        "decision_types": [{"name": t.name, "sort_order": t.sort_order} for t in own_types],
        "decisions": entries,
        _LINKS_KEY: export_artefact_links(db, project, {DECISION_ARTEFACT_TYPE: {d.id: d.unique_code for d in decisions}}),
    }, assets


def import_project_data(
    db: Session, project: Project, data: dict[str, Any], file_bytes_by_ref: dict[str, bytes], current_user: User,
    users: UserResolver, warnings: BundleImportWarnings,
) -> None:
    """`ModuleProjectBundleHooks.import_`: recreates the project's Decision types and Decisions
    (numbered afresh) with attachments, tags and links. A user or group the target cannot match
    is replaced or left unset with a warning, never guessed."""
    if not data.get("decisions") and not data.get("decision_types"):
        return
    organization_id = project.organization_id
    types: dict[str, DecisionTypeDefinition] = {}
    for t in data.get("decision_types", []):
        row = DecisionTypeDefinition(project_id=project.id, name=t["name"], sort_order=t.get("sort_order", len(types)))
        db.add(row)
        types[t["name"]] = row
    db.flush()

    by_ref: dict[str, uuid.UUID] = {}
    for entry in data.get("decisions", []):
        context = f"Decision {entry['ref']}"
        type_name = entry.get("type_name")
        if type_name not in types:
            row = DecisionTypeDefinition(project_id=project.id, name=type_name or "Imported", sort_order=len(types))
            db.add(row)
            db.flush()
            types[row.name] = row
            type_name = row.name
        creator_id = users.resolve(entry.get("created_by_email"), required=True, context=f"{context} creator")
        archived = bool(entry.get("is_archived"))
        archiver = users.resolve(entry.get("archived_by_email"), required=False, context=f"{context} archiver")
        maker = principal_columns_from_bundle(
            db, entry, "decision_maker", organization_id=organization_id, project_id=project.id, users=users,
            warnings=warnings, context=f"{context} decision maker", required=False,
        )
        decision = Decision(
            project_id=project.id, unique_code=generate_unique_code(db, project, DECISION_ARTEFACT_TYPE, DECISION_CODE_PREFIX),
            title=entry["title"], decision_statement=entry["decision_statement"], decision_type_id=types[type_name].id,
            status=DecisionStatus(entry.get("status", "draft")), decision_date=_date(entry.get("decision_date")),
            **maker,
            **principal_columns_from_bundle(
                db, entry, "owner", organization_id=organization_id, project_id=project.id, users=users, warnings=warnings,
                context=f"{context} owner", required=True,
            ),
            **{f: entry.get(f) for f in _TEXT_FIELDS}, creator_id=creator_id, is_archived=archived,
            archived_at=_dt(entry.get("archived_at")), archived_by=(archiver or creator_id) if archived else None,
        )
        db.add(decision)
        db.flush()
        by_ref[entry["ref"]] = decision.id
        restore_record_tags(
            db, organization_id=organization_id, record_project_id=project.id, actor_id=creator_id,
            artefact_type=DECISION_ARTEFACT_TYPE, artefact_id=decision.id, names=entry.get("tags"),
        )
        import_file_links(
            db, organization_id=organization_id, file_model=DecisionFile, fk="decision_id", record_id=decision.id,
            entries=entry.get("attachments", []), file_bytes_by_ref=file_bytes_by_ref, current_user=current_user,
            users=users, context=context,
        )

    import_artefact_links(
        db, project, data.get(_LINKS_KEY, []), {DECISION_ARTEFACT_TYPE: by_ref}, current_user, users, warnings,
        context="Decisions",
    )
    db.flush()
