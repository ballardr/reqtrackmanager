"""
Module: services.change_request_list

The change request list query, shared by the list endpoint (`routers.change_requests.core`) and the record
table (`services.record_tables_core`), so a filter added here reaches the page and the file together.

Responsibilities:
- Select a project's change requests by status, newest first (`query_change_requests`).
- Load each one's latest version in one query (`latest_versions`).
- Narrow by proposed target stage and free-text search (`narrow_change_requests`).

Design decisions:
- Tags and the nested-project scope are not applied here: the endpoint and the table engine already apply
  them generically (`TagFilter`, `ProjectScope`).
- Search matches what the list shows: the request's code, the proposed name, the reason, and the target
  requirement's code and current name (loaded in one batched query).

Dependencies: `models.change_request`, `models.requirement`.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.change_request import ChangeRequest, ChangeRequestVersion
from app.models.enums import ChangeRequestStatus
from app.models.requirement import Requirement, RequirementVersion

#: The statuses `active_only` keeps: everything not yet decided or withdrawn.
ACTIVE_STATUSES = (ChangeRequestStatus.DRAFT, ChangeRequestStatus.SUBMITTED, ChangeRequestStatus.IN_REVIEW)


def count_change_requests(db: Session, project_id: uuid.UUID) -> int:
    """How many change requests the project has, before any filter.

    Args:
        db: Active session (read only).
        project_id: The project.

    Returns:
        The count.
    """
    return db.scalar(select(func.count()).select_from(ChangeRequest).where(ChangeRequest.project_id == project_id)) or 0


def query_change_requests(
    db: Session, project_id: uuid.UUID, *, cr_status: ChangeRequestStatus | None = None, active_only: bool = False,
) -> list[ChangeRequest]:
    """A project's change requests, newest first, optionally narrowed by status.

    Args:
        db: Active session (read only).
        project_id: The project.
        cr_status: Keep only this status. Wins over `active_only`: an explicit status is more specific.
        active_only: Keep only draft, submitted and in-review requests.

    Returns:
        The change requests; the creation time then id order makes `limit`/`offset` pages stable.
    """
    query = select(ChangeRequest).where(ChangeRequest.project_id == project_id)
    if cr_status:
        query = query.where(ChangeRequest.status == cr_status)
    elif active_only:
        query = query.where(ChangeRequest.status.in_(ACTIVE_STATUSES))
    return list(db.scalars(query.order_by(ChangeRequest.created_at.desc(), ChangeRequest.id.desc())).all())


def latest_versions(db: Session, change_requests: Sequence[ChangeRequest]) -> dict[uuid.UUID, ChangeRequestVersion]:
    """Each change request's most recent version, in one query.

    Args:
        db: Active session (read only).
        change_requests: The requests.

    Returns:
        `{change request id: latest version}`.
    """
    ids = [cr.id for cr in change_requests]
    if not ids:
        return {}
    newest: dict[uuid.UUID, ChangeRequestVersion] = {}
    for version in db.scalars(select(ChangeRequestVersion).where(ChangeRequestVersion.change_request_id.in_(ids))).all():
        held = newest.get(version.change_request_id)
        if held is None or version.version_number > held.version_number:
            newest[version.change_request_id] = version
    return newest


def narrow_change_requests(
    db: Session, change_requests: Sequence[ChangeRequest], *, target_stage_id: uuid.UUID | None = None, search: str | None = None,
) -> list[tuple[ChangeRequest, ChangeRequestVersion]]:
    """Pairs each request with its latest version, keeping those that match the stage and the search.

    Args:
        db: Active session (read only).
        change_requests: The requests, already narrowed by status (and tags).
        target_stage_id: Keep only requests proposing this target stage.
        search: Case-insensitive substring over the code, proposed name, reason, and the target requirement's
            code and name.

    Returns:
        `(request, latest version)` pairs in the order given.
    """
    versions = latest_versions(db, change_requests)
    needle = search.strip().lower() if search and search.strip() else None
    requirement_text: dict[uuid.UUID, str] = {}
    if needle:
        requirement_ids = {cr.requirement_id for cr in change_requests if cr.requirement_id}
        if requirement_ids:
            for requirement_id, code, name in db.execute(
                select(Requirement.id, Requirement.unique_code, RequirementVersion.name)
                .join(RequirementVersion, RequirementVersion.requirement_id == Requirement.id)
                .where(Requirement.id.in_(requirement_ids), RequirementVersion.valid_to.is_(None))
            ).all():
                requirement_text[requirement_id] = f"{code} {name}".lower()
    kept: list[tuple[ChangeRequest, ChangeRequestVersion]] = []
    for cr in change_requests:
        version = versions[cr.id]
        if target_stage_id and version.proposed_target_stage_id != target_stage_id:
            continue
        if needle:
            haystack = " ".join(filter(None, [
                cr.unique_code.lower(), (version.proposed_name or "").lower(), (version.reason or "").lower(),
                requirement_text.get(cr.requirement_id, "") if cr.requirement_id else "",
            ]))
            if needle not in haystack:
                continue
        kept.append((cr, version))
    return kept
