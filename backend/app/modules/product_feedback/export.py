"""
Module: modules.product_feedback.export

This module's contribution to the core org/project bundle export/import (`services.org_export` /
`project_export`), registered through `ModuleOrgBundleHooks` / `ModuleProjectBundleHooks` on `MODULE_DEFINITION`
rather than those core files importing this module.

- Org level: the organisation's inbox requests.
- Project level: the project's submission policy and its requests (current content and status, tags and
  evidence attachments).

Design decisions (all Decided by: Agent):
- A request travels as its *current* content and status only. Version history, comments and comment
  attachments are not carried: a bundle is a migration artefact, and the imported request starts at version 1
  attributed to the importer where the author cannot be matched.
- The `ENH-nnn` code is carried as information only; an import numbers its records afresh from the target's
  counter, so a restored project can never collide with a code it already uses.
- An owner is `{type, email | name}` (`services.principals`); one the target cannot match is left unset with a
  warning. Org-level files cannot travel (the org hook receives no bytes).
- The org-level merge skips an inbox request whose title and description the organisation already holds, so a
  re-import is idempotent.

Dependencies: `services.bundle_common`, `services.principals`, `services.tags`, this module's models and service.
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
from app.modules.product_feedback.enums import EnhancementRequestScope, EnhancementRequestStatus, SubmissionPolicy
from app.modules.product_feedback.models import (
    EnhancementRequest,
    EnhancementRequestFile,
    EnhancementRequestVersion,
    ProjectFeedbackSettings,
)
from app.modules.product_feedback.service import (
    REQUEST_ARTEFACT_TYPE,
    REQUEST_CODE_PREFIX,
    RecordOwner,
    set_submission_policy,
)
from app.services.bundle_common import BundleImportWarnings, UserResolver, export_file_links, import_bundled_file, prime_file_links
from app.services.principals import principal_columns_from_bundle, principal_to_bundle
from app.services.sequences import code_owner, generate_unique_code
from app.services.tags import prime_record_tag_names, record_tag_names, restore_record_tags


def _j(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _emails(db: Session, user_ids: set[UUID | None]) -> dict[UUID, str]:
    ids = {u for u in user_ids if u is not None}
    return {u.id: u.email for u in db.scalars(select(User).where(User.id.in_(ids)))} if ids else {}


def _export_requests(
    db: Session, pairs: list[tuple[EnhancementRequest, EnhancementRequestVersion]], assets: dict[UUID, FileAsset] | None,
) -> list[dict[str, Any]]:
    """The bundle rows of `(request, current version)` pairs; attachments only when `assets` is given."""
    ids = [r.id for r, _ in pairs]
    prime_record_tag_names(db, REQUEST_ARTEFACT_TYPE, ids)
    if assets is not None:
        prime_file_links(db, EnhancementRequestFile, "request_id", ids)
    emails = _emails(db, {u for r, v in pairs for u in (r.creator_id, r.archived_by, v.created_by)})
    out = []
    for request, version in pairs:
        entry: dict[str, Any] = {
            "unique_code": request.unique_code, "title": version.title, "description": version.description,
            "status": version.status.value, "decline_reason": version.decline_reason,
            "external_ref_url": version.external_ref_url, "external_ref_key": version.external_ref_key,
            "owner": principal_to_bundle(db, version.owner_type, version.owner_id),
            "created_by_email": emails.get(request.creator_id), "created_at": _j(request.created_at),
            "is_archived": request.is_archived, "archived_at": _j(request.archived_at),
            "archived_by_email": emails.get(request.archived_by) if request.archived_by else None,
            "tags": record_tag_names(db, REQUEST_ARTEFACT_TYPE, request.id),
        }
        if assets is not None:
            entry["attachments"] = export_file_links(db, EnhancementRequestFile, "request_id", request.id, assets)
        out.append(entry)
    return out


def _import_request(
    db: Session, holder: RecordOwner, entry: dict[str, Any], users: UserResolver, warnings: BundleImportWarnings,
    current_user: User | None, file_bytes_by_ref: dict[str, bytes] | None,
) -> EnhancementRequest:
    """Creates one request (numbered afresh) with its version 1, tags and attachments."""
    context = entry.get("unique_code", "request")
    creator_id = users.resolve(entry.get("created_by_email"), required=True, context=f"Request {context} creator")
    archived = bool(entry.get("is_archived"))
    archiver_id = users.resolve(entry.get("archived_by_email"), required=False, context=f"Request {context} archiver")
    owner = code_owner(
        db, is_org_scope=not holder.is_project, organization_id=holder.organization_id, project_id=holder.project_id,
    )
    request = EnhancementRequest(
        scope=holder.scope, organization_id=None if holder.is_project else holder.organization_id,
        project_id=holder.project_id, creator_id=creator_id, is_archived=archived,
        archived_at=_dt(entry.get("archived_at")), archived_by=(archiver_id or creator_id) if archived else None,
        unique_code=generate_unique_code(db, owner, REQUEST_ARTEFACT_TYPE, REQUEST_CODE_PREFIX),
    )
    db.add(request)
    db.flush()
    now = datetime.now(UTC)
    db.add(EnhancementRequestVersion(
        request_id=request.id, version_number=1, valid_from=now, valid_to=None, title=entry["title"],
        description=entry.get("description", ""), status=EnhancementRequestStatus(entry.get("status", "new")),
        external_ref_url=entry.get("external_ref_url"), external_ref_key=entry.get("external_ref_key"),
        decline_reason=entry.get("decline_reason", ""),
        **principal_columns_from_bundle(
            db, entry, "owner", organization_id=holder.organization_id, project_id=holder.project_id, users=users,
            warnings=warnings, context=f"Request {context} owner", required=False,
        ),
        change_note="Imported from bundle.", created_by=creator_id, created_at=now,
    ))
    db.flush()
    restore_record_tags(
        db, organization_id=holder.organization_id, record_project_id=holder.project_id, actor_id=creator_id,
        artefact_type=REQUEST_ARTEFACT_TYPE, artefact_id=request.id, names=entry.get("tags"),
    )
    for attachment in entry.get("attachments", []):
        data = (file_bytes_by_ref or {}).get(attachment["file_ref"])
        if data is None:
            continue
        uploader_id = users.resolve(
            attachment.get("linked_by_email"), required=False, context="Request attachment uploader",
        ) or (current_user.id if current_user is not None else None)
        if uploader_id is None:
            continue
        asset = import_bundled_file(
            db, organization_id=holder.organization_id, uploaded_by=uploader_id, filename=attachment["filename"],
            content_type=attachment.get("content_type") or "application/octet-stream", data=data,
            confidential=bool(attachment.get("confidential")),
        )
        db.add(EnhancementRequestFile(request_id=request.id, file_id=asset.id, linked_by=uploader_id, created_at=now))
    return request


# --- Org level ---------------------------------------------------------------


def export_org_data(db: Session, org: Organization) -> dict[str, Any]:
    """`ModuleOrgBundleHooks.export`: the organisation's inbox requests (archived included: a bundle is a backup)."""
    pairs = db.execute(
        select(EnhancementRequest, EnhancementRequestVersion)
        .join(EnhancementRequestVersion, EnhancementRequestVersion.request_id == EnhancementRequest.id)
        .where(
            EnhancementRequest.organization_id == org.id,
            EnhancementRequest.scope == EnhancementRequestScope.ORGANIZATION,
            EnhancementRequestVersion.valid_to.is_(None),
        ).order_by(EnhancementRequest.unique_code)
    ).all()
    return {"enhancement_requests": _export_requests(db, [tuple(p) for p in pairs], None)}


def import_org_data(
    db: Session, org: Organization, data: dict[str, Any], users: UserResolver, warnings: BundleImportWarnings,
    resolutions: dict[str, str] | None,
) -> None:
    """`ModuleOrgBundleHooks.import_`: recreates the inbox requests, skipping one the organisation already holds."""
    existing = {
        (v.title, v.description)
        for v in db.scalars(
            select(EnhancementRequestVersion).join(EnhancementRequest, EnhancementRequest.id == EnhancementRequestVersion.request_id)
            .where(
                EnhancementRequest.organization_id == org.id, EnhancementRequestVersion.valid_to.is_(None),
            )
        )
    }
    for entry in data.get("enhancement_requests", []):
        key = (entry["title"], entry.get("description", ""))
        if key in existing:
            warnings.add(f"Inbox request {entry['title']!r} skipped — the organisation already has one like it.")
            continue
        existing.add(key)
        _import_request(db, RecordOwner(org.id), entry, users, warnings, None, None)
    db.flush()


# --- Project level -----------------------------------------------------------


def export_project_data(db: Session, project: Project) -> tuple[dict[str, Any], dict[UUID, FileAsset]]:
    """`ModuleProjectBundleHooks.export`: the project's settings and requests with attachments (archived included)."""
    assets: dict[UUID, FileAsset] = {}
    pairs = db.execute(
        select(EnhancementRequest, EnhancementRequestVersion)
        .join(EnhancementRequestVersion, EnhancementRequestVersion.request_id == EnhancementRequest.id)
        .where(EnhancementRequest.project_id == project.id, EnhancementRequestVersion.valid_to.is_(None))
        .order_by(EnhancementRequest.unique_code)
    ).all()
    settings = db.scalar(select(ProjectFeedbackSettings).where(ProjectFeedbackSettings.project_id == project.id))
    return {
        "feedback_settings": {"submission_policy": settings.submission_policy.value} if settings else None,
        "enhancement_requests": _export_requests(db, [tuple(p) for p in pairs], assets),
    }, assets


def import_project_data(
    db: Session, project: Project, data: dict[str, Any], file_bytes_by_ref: dict[str, bytes], current_user: User,
    users: UserResolver, warnings: BundleImportWarnings,
) -> None:
    """`ModuleProjectBundleHooks.import_`: recreates the project's settings and requests (numbered afresh)."""
    settings = data.get("feedback_settings")
    if settings:
        set_submission_policy(db, project.id, SubmissionPolicy(settings["submission_policy"]))
    holder = RecordOwner.of_project(project)
    for entry in data.get("enhancement_requests", []):
        _import_request(db, holder, entry, users, warnings, current_user, file_bytes_by_ref)
    db.flush()
