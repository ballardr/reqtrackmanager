"""
Module: routers.requirements.workflow

Requirement review/approval/completion lifecycle transitions: due-review
listing (C-R-09), recording a scheduled review outcome (C-R-07), direct
approval out of draft/reviewed (C-G-11), and marking an approved requirement
completed/uncompleted (C-P-03, C-G-11).
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user, get_request_channel
from app.models.enums import PrincipalType, ProjectRole, RequirementReviewOutcome, RequirementStatus
from app.models.project import Project, ProjectComponent
from app.models.requirement import Requirement, RequirementReview
from app.models.user import User
from app.routers.requirements.core import REQUIRES_APPROVAL_STATUSES, _to_out, require_requirement_approver
from app.schemas.requirement import (
    RequirementApproveRequest,
    RequirementDueForReviewOut,
    RequirementOut,
    RequirementReviewCreate,
    RequirementReviewOut,
)
from app.services import approval_separation, pubsub, review_engine
from app.services.audit import log_event
from app.services.lookups import project_or_404
from app.services.principals import is_principal_member, label_of, principal_ref
from app.services.rbac import get_effective_project_roles, require_ai_approvals_enabled, require_project_manage, require_project_view
from app.services.requirements import apply_new_version, check_status_move, get_current_version, get_current_version_for_update
from app.services.reviews import get_due_reviews_for_project, reviewer_labels

router = APIRouter(tags=["requirements-workflow"])


@router.get("/reviews/due", response_model=list[RequirementDueForReviewOut])
def list_due_reviews(
    project_id: UUID,
    component_id: UUID | None = None,
    reviewer_type: PrincipalType = PrincipalType.USER,
    reviewer_id: UUID | None = None,
    reviewer_mine: bool = False,
    current_user: User = Depends(require_project_view),
    db: Session = Depends(get_db),
):
    """Requirements due/overdue for review in this project, project-basis (C-R-09).

    Registered before `GET /{requirement_id}` so this static path isn't
    swallowed by that dynamic route (same reasoning as `/import` above).
    Supports an optional filter panel for projects with enough due reviews that a flat
    list stops being scannable: `component_id`, a specific reviewer (`reviewer_type` +
    `reviewer_id`: a user, an organisation group or a project group), or `reviewer_mine`
    (reviews assigned to the caller or to a group they belong to).
    """
    due = get_due_reviews_for_project(db, project_id)
    if component_id is not None:
        due = [(version, req) for version, req in due if req.component_id == component_id]
    if reviewer_id is not None:
        due = [
            (version, req) for version, req in due
            if version.reviewer_type == reviewer_type.value and version.reviewer_id == reviewer_id
        ]
    if reviewer_mine:
        due = [
            (version, req) for version, req in due
            if is_principal_member(db, principal_ref(version.reviewer_type, version.reviewer_id), current_user.id)
        ]

    reviewers = reviewer_labels(db, [version for version, _ in due])
    component_ids = {req.component_id for _, req in due}
    component_names = (
        dict(db.execute(select(ProjectComponent.id, ProjectComponent.name).where(ProjectComponent.id.in_(component_ids))).tuples().all())
        if component_ids
        else {}
    )

    return [
        RequirementDueForReviewOut(
            requirement_id=req.id, project_id=req.project_id, unique_code=req.unique_code,
            name=version.name, review_date=version.review_date,
            reviewer=label_of(reviewers, version.reviewer_type, version.reviewer_id),
            component_id=req.component_id, component_name=component_names.get(req.component_id, ""),
        )
        for version, req in due
        if version.review_date is not None
    ]


@router.post("/{requirement_id}/reviews", response_model=RequirementReviewOut, status_code=status.HTTP_201_CREATED)
def record_review_outcome(
    project_id: UUID, requirement_id: UUID, payload: RequirementReviewCreate,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    """Records the outcome of a requirement's scheduled review (C-R-07).

    Gate: the requirement's assigned reviewer (C-R-10; when that is a group, any one of its members, recorded as
    `reviewed_by`), the review policy's default owner when the requirement has no reviewer, or a project manager as a
    fallback. Does not touch `review_date` (see `services/reviews.py`'s
    due-list definition): the requirement leaves the due list because a review now exists.

    A `FAILED` outcome against a currently completed requirement also clears its completion overlay
    (`is_completed`/`completed_at`/`completed_by`), C-G-11's "may later be reversed to non-compliant when a
    review/audit occurs". It is logged as a distinct audit event (`completion_cleared_by_review`) from
    `review_recorded`, so the reviewer's outcome is traceable as the cause.
    """
    requirement = db.get(Requirement, requirement_id)
    if requirement is None or requirement.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Requirement not found.")
    version = get_current_version(db, requirement.id)
    is_reviewer = is_principal_member(db, principal_ref(version.reviewer_type, version.reviewer_id), current_user.id)
    is_manager = ProjectRole.PROJECT_MANAGER in get_effective_project_roles(db, current_user.id, project_id)
    if not (is_reviewer or is_manager or review_engine.may_review_as_default_owner(
        db, current_user.id, project_id, "requirement", principal_ref(version.reviewer_type, version.reviewer_id),
    )):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Only the assigned reviewer (or a member of the reviewer group) or a project manager may record this.",
        )
    if payload.outcome == RequirementReviewOutcome.FAILED and not (payload.comment or "").strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A comment is required when the outcome is 'failed'.")

    review = RequirementReview(
        requirement_id=requirement.id, requirement_version_id=version.id,
        reviewed_by=current_user.id, reviewed_at=datetime.now(UTC),
        outcome=payload.outcome, comment=payload.comment,
    )
    db.add(review)
    log_event(db, entity_type="requirement", entity_id=requirement.id, action="review_recorded",
              actor_id=current_user.id, project_id=project_id, detail={"outcome": payload.outcome.value})
    if payload.outcome == RequirementReviewOutcome.FAILED and requirement.is_completed:
        requirement.is_completed = False
        requirement.completed_at = None
        requirement.completed_by = None
        log_event(db, entity_type="requirement", entity_id=requirement.id, action="completion_cleared_by_review",
                  actor_id=current_user.id, project_id=project_id, detail={"reason": "failed_review_outcome"})
    db.commit()
    db.refresh(review)
    return RequirementReviewOut(
        id=review.id, requirement_id=review.requirement_id, reviewed_by=review.reviewed_by,
        reviewed_at=review.reviewed_at, outcome=review.outcome, comment=review.comment,
    )


@router.post("/{requirement_id}/approve", response_model=RequirementOut)
def approve_requirement(
    project_id: UUID, requirement_id: UUID, payload: RequirementApproveRequest | None = None,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
    channel: str = Depends(get_request_channel),
):
    """Approves a draft or reviewed requirement directly (C-G-11): the standalone path out of draft/reviewed
    status. `APPROVED` is otherwise reached through a change request (`decide_change_request`), a stage baseline
    (`services/baseline.py::create_baseline_for_stage`) or a full edit payload by a project manager
    (`update_requirement`). This single-purpose action matches `complete`/`uncomplete` below, so the frontend
    need not resend the whole edit payload to change status.

    Gate: project manager (C-U-03's clarification: Project Managers provide approvals for change requests
    and for project requirements from scoping review), a holder of the requirement `approve_baseline` permission or
    a role the project's approval policy names (`require_requirement_approver`, the check `decide_change_request`'s
    twin and `update_requirement`'s status=approved branch use). Through the MCP server (`channel == "mcp"`) the project
    and its organisation must also have enabled AI approval (docs/decisions.md's "AI approval via MCP" entry);
    a UI/API call is unaffected.

    The body is optional; its `comment` (what the approver checked) is recorded as the audit event's
    `detail.comment` and appended to the version's change note, so it shows in the Activity tab and the
    Versions table.
    """
    project = project_or_404(db, project_id)
    require_requirement_approver(db, current_user, project)
    requirement = db.get(Requirement, requirement_id)
    if requirement is None or requirement.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Requirement not found.")
    if channel == "mcp":
        require_ai_approvals_enabled(db, project)
    current_version = get_current_version_for_update(db, requirement.id)
    if current_version.status not in REQUIRES_APPROVAL_STATUSES:
        raise HTTPException(status.HTTP_409_CONFLICT, "Only a draft or reviewed requirement can be approved.")
    check_status_move(db, project_id, requirement.id, current_version.status, RequirementStatus.APPROVED)
    comment = ((payload.comment if payload else None) or "").strip()
    approval_separation.enforce_approval(
        db, user=current_user, artefact_type="requirement", record_id=requirement.id, creator_id=requirement.creator_id,
        organization_id=project.organization_id, project_id=project_id, comment=comment,
    )
    note = "Approved via MCP" if channel == "mcp" else "Approved directly"
    new_version = apply_new_version(
        db, requirement, current_version, current_user,
        status_value=RequirementStatus.APPROVED,
        change_note=f"{note}: {comment}" if comment else f"{note}.",
    )
    detail: dict[str, str] = {}
    if channel == "mcp":
        detail["via"] = "mcp"
    if comment:
        detail["comment"] = comment
    log_event(db, entity_type="requirement", entity_id=requirement.id, action="approved",
              actor_id=current_user.id, project_id=project_id, detail=detail or None)
    db.commit()
    db.refresh(requirement)
    pubsub.notify(project_id, {"type": "requirement", "action": "approved", "id": str(requirement.id)})
    return _to_out(db, requirement, new_version, current_user.id)


@router.post("/{requirement_id}/complete", response_model=RequirementOut)
def complete_requirement(
    project_id: UUID, requirement_id: UUID,
    current_user: User = Depends(get_current_user), project: Project = Depends(require_project_manage),
    db: Session = Depends(get_db), channel: str = Depends(get_request_channel),
):
    """Marks an approved requirement completed (C-P-03, C-G-11), gated as archiving is: a status transition a
    project manager makes directly, not content that goes through a change request. Through the MCP server the
    project and its organisation must also have enabled AI approval (see `approve_requirement`).

    Sets `is_completed`/`completed_at`/`completed_by` on the `Requirement` row without `apply_new_version`:
    completion is an overlay marker independent of lifecycle state (C-G-11), not a content change, so it must
    not bump the version number.
    """
    requirement = db.get(Requirement, requirement_id)
    if requirement is None or requirement.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Requirement not found.")
    if channel == "mcp":
        require_ai_approvals_enabled(db, project)
    current_version = get_current_version(db, requirement.id)
    if current_version.status != RequirementStatus.APPROVED:
        raise HTTPException(status.HTTP_409_CONFLICT, "Only an approved requirement can be marked completed.")
    if requirement.is_completed:
        raise HTTPException(status.HTTP_409_CONFLICT, "This requirement is already marked completed.")
    requirement.is_completed = True
    requirement.completed_at = datetime.now(UTC)
    requirement.completed_by = current_user.id
    log_event(db, entity_type="requirement", entity_id=requirement.id, action="completed",
              actor_id=current_user.id, project_id=project_id,
              detail={"via": "mcp"} if channel == "mcp" else None)
    db.commit()
    db.refresh(requirement)
    return _to_out(db, requirement, current_version, current_user.id)


@router.post("/{requirement_id}/uncomplete", response_model=RequirementOut)
def uncomplete_requirement(
    project_id: UUID, requirement_id: UUID,
    current_user: User = Depends(get_current_user), project: Project = Depends(require_project_manage),
    db: Session = Depends(get_db),
):
    """Reverts a completed requirement's completion overlay, to correct a
    mistake — the requirement's lifecycle `status` was never changed by
    `complete_requirement` in the first place (it stays `approved`
    throughout), so this only clears `is_completed`/`completed_at`/
    `completed_by`, again without creating a new version."""
    requirement = db.get(Requirement, requirement_id)
    if requirement is None or requirement.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Requirement not found.")
    current_version = get_current_version(db, requirement.id)
    if not requirement.is_completed:
        raise HTTPException(status.HTTP_409_CONFLICT, "This requirement is not marked completed.")
    requirement.is_completed = False
    requirement.completed_at = None
    requirement.completed_by = None
    log_event(db, entity_type="requirement", entity_id=requirement.id, action="uncompleted",
              actor_id=current_user.id, project_id=project_id)
    db.commit()
    db.refresh(requirement)
    return _to_out(db, requirement, current_version, current_user.id)
