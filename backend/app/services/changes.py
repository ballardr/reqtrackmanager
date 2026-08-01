"""
Module: services.changes

Builds the unified "project changes over time" timeline (C-A-10) by merging
three sources: generic audit events (group/role/project-structure changes),
requirement version history, and change-request version history. Discussion
comments (C-R-01) are excluded by default per the requirement's
clarification — the caller can opt in via `include_comments`.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.audit import AuditEvent
from app.models.change_request import ChangeRequest, ChangeRequestVersion, ReviewComment
from app.models.enums import ReviewTargetType
from app.models.requirement import Requirement, RequirementVersion
from app.schemas.changes import ChangeEntryOut


def get_project_changes(
    db: Session, project_id: UUID, *, since: datetime | None, until: datetime | None, include_comments: bool = False
) -> list[ChangeEntryOut]:
    """Returns a unified, time-ordered list of changes for a project.

    Args:
        db: An active database session.
        project_id: The project to report on.
        since / until: Optional inclusive time range filter.
        include_comments: Whether to include discussion-thread comments
            (excluded by default, per C-A-10's clarification).

    Returns:
        Entries sorted newest-first.
    """
    entries: list[ChangeEntryOut] = []

    audit_query = select(AuditEvent).where(AuditEvent.project_id == project_id)
    if since is not None:
        audit_query = audit_query.where(AuditEvent.created_at >= since)
    if until is not None:
        audit_query = audit_query.where(AuditEvent.created_at <= until)
    for event in db.scalars(audit_query).all():
        entries.append(
            ChangeEntryOut(
                timestamp=event.created_at, entity_type=event.entity_type, entity_id=event.entity_id,
                action=event.action, actor_id=event.actor_id, detail=event.detail,
            )
        )

    req_version_query = (
        select(RequirementVersion, Requirement.unique_code)
        .join(Requirement, Requirement.id == RequirementVersion.requirement_id)
        .where(Requirement.project_id == project_id)
    )
    if since is not None:
        req_version_query = req_version_query.where(RequirementVersion.created_at >= since)
    if until is not None:
        req_version_query = req_version_query.where(RequirementVersion.created_at <= until)
    for version, unique_code in db.execute(req_version_query).all():
        action = "created" if version.version_number == 1 else "updated"
        entries.append(
            ChangeEntryOut(
                timestamp=version.created_at, entity_type="requirement", entity_id=str(version.requirement_id),
                action=action, actor_id=version.created_by,
                detail={"unique_code": unique_code, "status": version.status.value, "change_note": version.change_note},
            )
        )

    cr_version_query = (
        select(ChangeRequestVersion, ChangeRequest.status)
        .join(ChangeRequest, ChangeRequest.id == ChangeRequestVersion.change_request_id)
        .where(ChangeRequest.project_id == project_id)
    )
    if since is not None:
        cr_version_query = cr_version_query.where(ChangeRequestVersion.created_at >= since)
    if until is not None:
        cr_version_query = cr_version_query.where(ChangeRequestVersion.created_at <= until)
    for version, cr_status in db.execute(cr_version_query).all():
        action = "created" if version.version_number == 1 else "updated"
        entries.append(
            ChangeEntryOut(
                timestamp=version.created_at, entity_type="change_request",
                entity_id=str(version.change_request_id), action=action, actor_id=version.created_by,
                detail={"proposed_name": version.proposed_name, "status": cr_status.value},
            )
        )

    if include_comments:
        comment_query = select(ReviewComment).where(
            ReviewComment.target_type.in_([ReviewTargetType.REQUIREMENT, ReviewTargetType.CHANGE_REQUEST])
        )
        # Comments don't carry project_id directly; scope via requirement/CR ids already in this project.
        requirement_ids = set(
            db.scalars(select(Requirement.id).where(Requirement.project_id == project_id)).all()
        )
        cr_ids = set(db.scalars(select(ChangeRequest.id).where(ChangeRequest.project_id == project_id)).all())
        relevant_ids = {str(i) for i in requirement_ids | cr_ids}
        if since is not None:
            comment_query = comment_query.where(ReviewComment.created_at >= since)
        if until is not None:
            comment_query = comment_query.where(ReviewComment.created_at <= until)
        for comment in db.scalars(comment_query).all():
            if str(comment.target_id) not in relevant_ids:
                continue
            entries.append(
                ChangeEntryOut(
                    timestamp=comment.created_at, entity_type=comment.target_type.value,
                    entity_id=str(comment.target_id), action="comment_added", actor_id=comment.author_id,
                    detail={"body": comment.body},
                )
            )

    entries.sort(key=lambda e: e.timestamp, reverse=True)
    return entries
