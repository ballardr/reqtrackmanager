"""
Module: modules.stakeholders.need_export

The Stakeholder Need part of this module's project bundle export/import
(`export.py` and `stakeholder_export.py` hold the Persona and Stakeholder
halves; `module.py` composes the three). A Need is project-scoped, so there is
no org-level half.

Design decisions:
- Same carry-over rules as the other halves: current content and status only,
  no version history or comments; cross-references use portable keys (a user's
  email, a Stakeholder/Persona's name and scope, a Requirement's unique code),
  never database ids.
- Needs import after the Persona and Stakeholder halves (so "has need" holders
  resolve) and, since the core import creates Requirements first, after
  Requirements too. A holder or Requirement the target lacks is skipped with a
  warning rather than failing the import.
- A Need can quote what a person said, so a bundle holding Needs is treated as
  Confidential like the Stakeholder half.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.file import FileAsset
from app.models.project import Project
from app.models.requirement import Requirement
from app.models.user import User
from app.modules.stakeholders.enums import NeedStatus, PersonaScope, StakeholderScope
from app.modules.stakeholders.models import Persona, Stakeholder, StakeholderNeed, StakeholderNeedFile
from app.modules.stakeholders.service import (
    STAKEHOLDER_ARTEFACT_TYPE,
    add_gives_rise_to_link,
    add_has_need_link,
    create_need,
    get_current_need_version,
    get_current_persona_version,
    get_current_stakeholder_version,
    list_need_holders,
    list_need_requirement_links,
)
from app.services.bundle_common import BundleImportWarnings, UserResolver, import_bundled_file

_TEXT_FIELDS = ("name", "description", "rationale")


def _j(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _need_json(db: Session, need: StakeholderNeed, project: Project, emails: dict[UUID, str]) -> dict[str, Any]:
    v = get_current_need_version(db, need.id)
    holders = []
    for _, kind, record in list_need_holders(db, need, project.organization_id):
        name = (
            get_current_stakeholder_version(db, record.id).name if kind == STAKEHOLDER_ARTEFACT_TYPE
            else get_current_persona_version(db, record.id).name
        )
        holders.append({"kind": kind, "name": name, "scope": record.scope.value})
    codes = []
    for link in list_need_requirement_links(db, need, project.organization_id):
        requirement = db.get(Requirement, link.target_id)
        if requirement is not None:
            codes.append(requirement.unique_code)
    return {
        **{f: getattr(v, f) for f in _TEXT_FIELDS}, "status": v.status.value, "owner_email": emails.get(v.owner_id),
        "created_by_email": emails.get(need.creator_id), "is_archived": need.is_archived,
        "archived_at": _j(need.archived_at), "created_at": _j(need.created_at), "holders": holders,
        "requirement_unique_codes": codes,
    }


def export_project_data(db: Session, project: Project) -> tuple[dict[str, Any], dict[UUID, FileAsset]]:
    """The project's needs with their holders, requirement codes and attachments."""
    needs = list(db.scalars(
        select(StakeholderNeed).where(StakeholderNeed.project_id == project.id).order_by(StakeholderNeed.created_at)
    ).all())
    user_ids = {need.creator_id for need in needs} | {get_current_need_version(db, n.id).owner_id for n in needs}
    user_ids.discard(None)
    emails = {u.id: u.email for u in db.scalars(select(User).where(User.id.in_(user_ids)))} if user_ids else {}
    assets: dict[UUID, FileAsset] = {}
    out = []
    for need in needs:
        entry = _need_json(db, need, project, emails)
        attachments = []
        for asset, linked_by in db.execute(
            select(FileAsset, User).join(StakeholderNeedFile, StakeholderNeedFile.file_id == FileAsset.id)
            .join(User, User.id == StakeholderNeedFile.linked_by).where(StakeholderNeedFile.need_id == need.id)
        ).all():
            assets[asset.id] = asset
            attachments.append({
                "file_ref": f"{asset.id}_{asset.filename}", "filename": asset.filename,
                "content_type": asset.content_type, "linked_by_email": linked_by.email,
            })
        entry["attachments"] = attachments
        out.append(entry)
    return {"project_stakeholder_needs": out}, assets


def import_project_data(
    db: Session, project: Project, data: dict[str, Any], file_bytes_by_ref: dict[str, bytes], current_user: User,
    users: UserResolver, warnings: BundleImportWarnings,
) -> None:
    """Recreates the project's needs, their holder and requirement links and
    attachments. Runs after the Persona and Stakeholder halves."""
    organization_id = project.organization_id
    stakeholders = {
        (get_current_stakeholder_version(db, s.id).name, s.scope.value): s.id
        for s in db.scalars(select(Stakeholder).where(
            ((Stakeholder.organization_id == organization_id) & (Stakeholder.scope == StakeholderScope.ORGANIZATION))
            | ((Stakeholder.project_id == project.id) & (Stakeholder.scope == StakeholderScope.PROJECT))
        ))
    }
    personas = {
        (get_current_persona_version(db, p.id).name, p.scope.value): p.id
        for p in db.scalars(select(Persona).where(
            ((Persona.organization_id == organization_id) & (Persona.scope == PersonaScope.ORGANIZATION))
            | ((Persona.project_id == project.id) & (Persona.scope == PersonaScope.PROJECT))
        ))
    }
    requirement_ids = {
        r.unique_code: r.id for r in db.scalars(select(Requirement).where(Requirement.project_id == project.id))
    }
    for n in data.get("project_stakeholder_needs", []):
        context = f"Stakeholder Need {n['name']!r}"
        creator_id = users.resolve(n.get("created_by_email"), required=True, context=f"{context} creator")
        creator = db.get(User, creator_id)
        need = create_need(
            db, project_id=project.id, creator=creator,
            owner_id=users.resolve(n.get("owner_email"), required=False, context=f"{context} owner"),
            **{f: n.get(f, "") for f in _TEXT_FIELDS},
        )
        version = get_current_need_version(db, need.id)
        version.status = NeedStatus(n.get("status", "draft"))
        version.change_note = "Imported from bundle."
        need.is_archived = bool(n.get("is_archived"))
        need.archived_at = _dt(n.get("archived_at"))
        need.archived_by = creator_id if need.is_archived else None
        db.flush()
        for holder in n.get("holders", []):
            lookup = stakeholders if holder["kind"] == STAKEHOLDER_ARTEFACT_TYPE else personas
            holder_id = lookup.get((holder["name"], holder["scope"]))
            if holder_id is None:
                warnings.add(f"{context}: holder {holder['name']!r} not found — link skipped.")
                continue
            try:
                add_has_need_link(db, holder["kind"], holder_id, need, current_user, organization_id=organization_id)
            except ValueError as exc:
                warnings.add(f"{context}: {exc}")
        for code in n.get("requirement_unique_codes", []):
            requirement_id = requirement_ids.get(code)
            if requirement_id is None:
                warnings.add(f"{context}: Requirement {code!r} not found — link skipped.")
                continue
            try:
                add_gives_rise_to_link(db, need, requirement_id, current_user, organization_id=organization_id)
            except ValueError as exc:
                warnings.add(f"{context}: {exc}")
        for att in n.get("attachments", []):
            att_bytes = file_bytes_by_ref.get(att["file_ref"])
            if att_bytes is None:
                continue
            uploader_id = (
                users.resolve(att.get("linked_by_email"), required=False, context="Stakeholder Need attachment uploader")
                or current_user.id
            )
            asset = import_bundled_file(
                db, organization_id=organization_id, uploaded_by=uploader_id, filename=att["filename"],
                content_type=att.get("content_type") or "application/octet-stream", data=att_bytes,
            )
            db.add(StakeholderNeedFile(need_id=need.id, file_id=asset.id, linked_by=uploader_id, created_at=datetime.now(UTC)))
    db.flush()
