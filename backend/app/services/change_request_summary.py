"""
Module: services.change_request_summary

Presents change requests as a linkable core artefact type, the way requirements and actions are.

Responsibilities:
- Title a change request (`change_request_titles`): its proposed name, else the name of the
  requirement it targets, else a generic label, so no list or link row is ever blank.
- Summarise change requests (`change_request_summaries`) as `"CR-001 title"` for the link graph,
  the link finder and the qualified-code lookup, reading only the rows asked for.
- Search a project's change requests (`change_request_candidates`) for the link finder.

Design decisions:
- A change request's label comes from its latest version (the one the detail page shows), not the
  first, because the name can be revised while it is a draft.
- Core code, not a module registration: change requests belong to core, so these helpers sit
  beside `link_graph`/`link_browse`, which call them where they already special-case the other
  two core types.

Dependencies: `models.change_request`, `models.requirement`, `modules.registry` (summary shape).
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.change_request import ChangeRequest, ChangeRequestVersion
from app.models.enums import ChangeRequestStatus
from app.models.requirement import Requirement, RequirementVersion
from app.modules.registry import ArtefactSummary

CHANGE_REQUEST_ARTEFACT_TYPE = "change_request"
CHANGE_REQUEST_CODE_PREFIX = "CR"
_FALLBACK_TITLE = "Change request"

#: Display labels for the status browse level; mirrors the frontend's `CHANGE_REQUEST_STATUS_LABEL`.
CHANGE_REQUEST_STATUS_LABEL: dict[str, str] = {
    ChangeRequestStatus.DRAFT.value: "Draft",
    ChangeRequestStatus.SUBMITTED.value: "Submitted",
    ChangeRequestStatus.IN_REVIEW.value: "In review",
    ChangeRequestStatus.APPROVED.value: "Approved",
    ChangeRequestStatus.REJECTED.value: "Rejected",
    ChangeRequestStatus.WITHDRAWN.value: "Withdrawn",
}


def change_request_titles(db: Session, change_requests: Sequence[ChangeRequest]) -> dict[uuid.UUID, str]:
    """Display titles of `change_requests`, in two queries however many are asked for.

    Args:
        db: Active session (read only).
        change_requests: The rows to title.

    Returns:
        `{change request id: title}`: the latest version's proposed name, else the target
        requirement's current name, else `"Change request"`.
    """
    if not change_requests:
        return {}
    ids = [cr.id for cr in change_requests]
    latest = (
        select(ChangeRequestVersion.change_request_id, func.max(ChangeRequestVersion.version_number).label("n"))
        .where(ChangeRequestVersion.change_request_id.in_(ids))
        .group_by(ChangeRequestVersion.change_request_id)
        .subquery()
    )
    proposed = {
        cr_id: name
        for cr_id, name in db.execute(
            select(ChangeRequestVersion.change_request_id, ChangeRequestVersion.proposed_name).join(
                latest,
                (latest.c.change_request_id == ChangeRequestVersion.change_request_id)
                & (latest.c.n == ChangeRequestVersion.version_number),
            )
        ).all()
    }
    requirement_ids = {cr.requirement_id for cr in change_requests if cr.requirement_id is not None}
    requirement_names: dict[uuid.UUID, str] = {}
    if requirement_ids:
        requirement_names = {
            requirement_id: name
            for requirement_id, name in db.execute(
                select(RequirementVersion.requirement_id, RequirementVersion.name).where(
                    RequirementVersion.requirement_id.in_(requirement_ids), RequirementVersion.valid_to.is_(None)
                )
            ).all()
        }
    return {
        cr.id: proposed.get(cr.id) or requirement_names.get(cr.requirement_id) or _FALLBACK_TITLE
        for cr in change_requests
    }


def _summaries(db: Session, change_requests: Sequence[ChangeRequest]) -> list[ArtefactSummary]:
    """`ArtefactSummary` for each row; a change request is never archived, only withdrawn."""
    titles = change_request_titles(db, change_requests)
    return [
        ArtefactSummary(
            id=cr.id, project_id=cr.project_id, label=f"{cr.unique_code} {titles[cr.id]}", status=cr.status.value,
            is_archived=False,
        )
        for cr in change_requests
    ]


def change_request_summaries(
    db: Session, project_ids: Sequence[uuid.UUID], ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, ArtefactSummary]:
    """Summaries of the change requests among `ids` that belong to any of `project_ids`.

    Args:
        db: Active session (read only).
        project_ids: Projects the caller may read the type in.
        ids: Change request ids to look up.

    Returns:
        `{id: summary}`; an id outside `project_ids` or not found is absent.
    """
    rows = db.scalars(
        select(ChangeRequest).where(ChangeRequest.id.in_(ids), ChangeRequest.project_id.in_(project_ids))
    ).all()
    return {s.id: s for s in _summaries(db, rows)}


def change_request_candidates(
    db: Session, project_id: uuid.UUID, selected: Mapping[str, str], needle: str, limit: int
) -> list[ArtefactSummary]:
    """Up to `limit` change requests of the project narrowed by status and by code or title.

    Args:
        db: Active session (read only).
        project_id: The project searched.
        selected: Chosen browse options; only `"status"` applies.
        needle: Lower-cased text matched against the code, the proposed name or the target
            requirement's name; empty matches all.
        limit: Maximum rows returned.

    Returns:
        Matching summaries, newest code first.
    """
    stmt = select(ChangeRequest).where(ChangeRequest.project_id == project_id)
    status_value = selected.get("status")
    if status_value in CHANGE_REQUEST_STATUS_LABEL:
        stmt = stmt.where(ChangeRequest.status == ChangeRequestStatus(status_value))
    if needle:
        like = f"%{needle}%"
        named = select(ChangeRequestVersion.change_request_id).where(ChangeRequestVersion.proposed_name.ilike(like))
        targeted = (
            select(ChangeRequest.id)
            .join(Requirement, Requirement.id == ChangeRequest.requirement_id)
            .join(RequirementVersion, RequirementVersion.requirement_id == Requirement.id)
            .where(RequirementVersion.valid_to.is_(None), RequirementVersion.name.ilike(like))
        )
        stmt = stmt.where(or_(ChangeRequest.unique_code.ilike(like), ChangeRequest.id.in_(named), ChangeRequest.id.in_(targeted)))
    return _summaries(db, db.scalars(stmt.order_by(ChangeRequest.unique_code.desc()).limit(limit)).all())
