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
from app.models.user import User
from app.schemas.changes import ChangeEntryOut


def get_project_changes(
    db: Session, project_id: UUID, *,
    since: datetime | None, until: datetime | None, include_comments: bool = False, entity_type: str | None = None,
) -> list[ChangeEntryOut]:
    """Returns a unified, time-ordered list of changes for a project.

    Args:
        db: An active database session.
        project_id: The project to report on.
        since / until: Optional inclusive time range filter.
        include_comments: Whether to include discussion-thread comments
            (excluded by default, per C-A-10's clarification).
        entity_type: Optional filter to a single entity type (e.g.
            "requirement", "change_request"). Applied after merging the
            three/four underlying sources rather than pushed into each
            query — none of them are large enough per-project for that to
            matter, and two of the sources (requirement/change-request
            version history) mint their `entity_type` in Python, not from a
            literal column, so filtering post-merge is both simpler and
            uniform across all sources.

    Returns:
        Entries sorted newest-first.
    """
    entries: list[ChangeEntryOut] = []

    # Every one of these (entity_type, action) pairs is logged by a router
    # handler that *also* calls `apply_new_version`/`create_requirement` (for
    # "requirement") or inserts the version-1 `ChangeRequestVersion` row (for
    # "change_request") in the same request — see requirements.py:196/632/
    # 768/797/821 and change_requests.py:343-364. The version-history queries
    # below already synthesize an equivalent, more informative entry for each
    # of these (carrying `change_note`, e.g. "Approved directly."), so the
    # generic `AuditEvent` row would otherwise show up a second time for the
    # same transition (UX review: duplicate activity-feed entries).
    # `archived`/`unarchived`/`review_recorded` (requirement) and
    # `submitted`/`withdrawn`/approve-reject (change_request) don't bump a
    # version and are unaffected.
    VERSION_HISTORY_COVERED_ACTIONS: dict[str, set[str]] = {
        "requirement": {"created", "updated", "approved", "completed", "uncompleted"},
        "change_request": {"created"},
    }

    audit_query = select(AuditEvent).where(AuditEvent.project_id == project_id)
    if since is not None:
        audit_query = audit_query.where(AuditEvent.created_at >= since)
    if until is not None:
        audit_query = audit_query.where(AuditEvent.created_at <= until)
    for event in db.scalars(audit_query).all():
        if event.action in VERSION_HISTORY_COVERED_ACTIONS.get(event.entity_type, set()):
            continue
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

    if entity_type is not None:
        entries = [e for e in entries if e.entity_type == entity_type]

    # Guarantees every requirement/change-request entry always carries a
    # resolvable id + current title (UI/UX pass: "link activity entries to
    # the item that changed, always showing its id and title") — not just
    # the entries sourced from version history above, which already had
    # `unique_code`/`proposed_name` in `detail`, but also the generic
    # `AuditEvent`-sourced ones (archive, review, file-attach, ...), whose
    # `detail` only ever contained whatever that specific call site happened
    # to log. Resolved from *current* state, not the state at the time of
    # the event, so a since-renamed item shows its current title everywhere
    # consistently rather than a stale one on some rows and not others.
    requirement_entries = [e for e in entries if e.entity_type == "requirement"]
    if requirement_entries:
        req_ids = {UUID(e.entity_id) for e in requirement_entries}
        unique_codes = dict(
            db.execute(select(Requirement.id, Requirement.unique_code).where(Requirement.id.in_(req_ids))).all()
        )
        current_names: dict[UUID, tuple[str, int]] = {}
        for req_id, name, version_number in db.execute(
            select(RequirementVersion.requirement_id, RequirementVersion.name, RequirementVersion.version_number)
            .where(RequirementVersion.requirement_id.in_(req_ids))
        ).all():
            if req_id not in current_names or version_number > current_names[req_id][1]:
                current_names[req_id] = (name, version_number)
        for e in requirement_entries:
            rid = UUID(e.entity_id)
            detail = dict(e.detail or {})
            if rid in unique_codes:
                detail["unique_code"] = unique_codes[rid]
            if rid in current_names:
                detail["name"] = current_names[rid][0]
            e.detail = detail

    cr_entries = [e for e in entries if e.entity_type == "change_request"]
    if cr_entries:
        cr_ids = {UUID(e.entity_id) for e in cr_entries}
        current_titles: dict[UUID, tuple[str | None, int]] = {}
        for cr_id, proposed_name, version_number in db.execute(
            select(ChangeRequestVersion.change_request_id, ChangeRequestVersion.proposed_name, ChangeRequestVersion.version_number)
            .where(ChangeRequestVersion.change_request_id.in_(cr_ids))
        ).all():
            if cr_id not in current_titles or version_number > current_titles[cr_id][1]:
                current_titles[cr_id] = (proposed_name, version_number)
        # A MODIFY_REQUIREMENT change request that doesn't propose changing
        # the name (changed_fields tracking, see docs/decisions.md's
        # "Change request field-level tracking" entry) has no proposed_name
        # of its own — fall back to the target requirement's own current
        # name so the activity feed still shows a real title instead of a
        # blank one, matching this block's own "always a resolvable
        # current title" intent. NEW_REQUIREMENT change requests always
        # have a real proposed_name (validated at creation), so this
        # fallback never triggers for those.
        missing_name_cr_ids = {cid for cid, (name, _) in current_titles.items() if name is None}
        fallback_names: dict[UUID, str] = {}
        if missing_name_cr_ids:
            cr_to_requirement = dict(
                db.execute(
                    select(ChangeRequest.id, ChangeRequest.requirement_id).where(ChangeRequest.id.in_(missing_name_cr_ids))
                ).all()
            )
            fallback_requirement_ids = {rid for rid in cr_to_requirement.values() if rid is not None}
            requirement_current_names: dict[UUID, tuple[str, int]] = {}
            if fallback_requirement_ids:
                for req_id, name, version_number in db.execute(
                    select(RequirementVersion.requirement_id, RequirementVersion.name, RequirementVersion.version_number)
                    .where(RequirementVersion.requirement_id.in_(fallback_requirement_ids))
                ).all():
                    if req_id not in requirement_current_names or version_number > requirement_current_names[req_id][1]:
                        requirement_current_names[req_id] = (name, version_number)
            for cr_id, requirement_id in cr_to_requirement.items():
                if requirement_id is not None and requirement_id in requirement_current_names:
                    fallback_names[cr_id] = requirement_current_names[requirement_id][0]
        for e in cr_entries:
            cid = UUID(e.entity_id)
            if cid in current_titles:
                detail = dict(e.detail or {})
                detail["proposed_name"] = current_titles[cid][0] or fallback_names.get(cid)
                e.detail = detail

    actor_ids = {e.actor_id for e in entries if e.actor_id is not None}
    display_names = {
        u.id: u.display_name for u in db.scalars(select(User).where(User.id.in_(actor_ids))).all()
    } if actor_ids else {}
    for e in entries:
        if e.actor_id is not None:
            e.actor_display_name = display_names.get(e.actor_id, "Unknown user")

    entries.sort(key=lambda e: e.timestamp, reverse=True)
    return entries
