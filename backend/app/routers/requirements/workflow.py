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
from app.models.enums import ProjectRole, RequirementReviewOutcome, RequirementStatus
from app.models.project import Project, ProjectComponent
from app.models.requirement import Requirement, RequirementReview
from app.models.user import User
from app.routers.requirements.core import REQUIRES_APPROVAL_STATUSES, _to_out
from app.schemas.requirement import RequirementDueForReviewOut, RequirementOut, RequirementReviewCreate, RequirementReviewOut
from app.services import pubsub
from app.services.audit import log_event
from app.services.rbac import get_effective_project_roles, require_ai_approvals_enabled, require_project_manage, require_project_view
from app.services.requirements import apply_new_version, get_current_version
from app.services.reviews import get_due_reviews_for_project

router = APIRouter(tags=["requirements-workflow"])


@router.get("/reviews/due", response_model=list[RequirementDueForReviewOut])
def list_due_reviews(
    project_id: UUID,
    component_id: UUID | None = None,
    reviewer_id: UUID | None = None,
    current_user: User = Depends(require_project_view),
    db: Session = Depends(get_db),
):
    """Requirements due/overdue for review in this project, project-basis (C-R-09).

    Registered before `GET /{requirement_id}` so this static path isn't
    swallowed by that dynamic route (same reasoning as `/import` above).
    Supports an optional filter panel (`component_id`/`reviewer_id`) for
    projects with enough due reviews that a flat list stops being scannable.
    """
    due = get_due_reviews_for_project(db, project_id)
    if component_id is not None:
        due = [(version, req) for version, req in due if req.component_id == component_id]
    if reviewer_id is not None:
        due = [(version, req) for version, req in due if version.reviewer_id == reviewer_id]

    reviewer_ids = {version.reviewer_id for version, _ in due if version.reviewer_id is not None}
    reviewer_names = (
        dict(db.execute(select(User.id, User.display_name).where(User.id.in_(reviewer_ids))).all())
        if reviewer_ids
        else {}
    )
    component_ids = {req.component_id for _, req in due}
    component_names = (
        dict(db.execute(select(ProjectComponent.id, ProjectComponent.name).where(ProjectComponent.id.in_(component_ids))).all())
        if component_ids
        else {}
    )

    return [
        RequirementDueForReviewOut(
            requirement_id=req.id, project_id=req.project_id, unique_code=req.unique_code,
            name=version.name, review_date=version.review_date, reviewer_id=version.reviewer_id,
            reviewer_name=reviewer_names.get(version.reviewer_id) if version.reviewer_id else None,
            component_id=req.component_id, component_name=component_names.get(req.component_id, ""),
        )
        for version, req in due
    ]


@router.post("/{requirement_id}/reviews", response_model=RequirementReviewOut, status_code=status.HTTP_201_CREATED)
def record_review_outcome(
    project_id: UUID, requirement_id: UUID, payload: RequirementReviewCreate,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    """Records the outcome of a requirement's scheduled review (C-R-07).

    Gate: the requirement's assigned reviewer (C-R-10), or a project manager
    as a fallback. Doesn't touch `review_date` itself (see
    `services/reviews.py`'s due-list definition) — the requirement drops off
    the due list because a review now exists, not because the date changed.

    A `FAILED` outcome recorded against a currently-completed requirement
    also clears its completion overlay (`is_completed`/`completed_at`/
    `completed_by`) — the concrete mechanism behind C-G-11's "[a requirement
    marked completed] may later be reversed to non-compliant... when a
    review/audit occurs." Logged as a distinct audit event
    (`completion_cleared_by_review`) from `review_recorded`, so it's
    traceable that the reviewer's outcome, not some other action, is what
    dropped the requirement back off the completed list.
    """
    requirement = db.get(Requirement, requirement_id)
    if requirement is None or requirement.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Requirement not found.")
    version = get_current_version(db, requirement.id)
    is_reviewer = version.reviewer_id == current_user.id
    is_manager = ProjectRole.PROJECT_MANAGER in get_effective_project_roles(db, current_user.id, project_id)
    if not (is_reviewer or is_manager):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the assigned reviewer or a project manager may record this.")
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
    project_id: UUID, requirement_id: UUID,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
    channel: str = Depends(get_request_channel),
):
    """Approves a draft or reviewed requirement directly (C-G-11) — the
    previously-missing standalone path out of draft/reviewed status (2026-08
    UX audit roadmap, "No requirement approval action"). Before this
    endpoint existed, `APPROVED` only ever happened as a side effect of a
    change request (`decide_change_request`) or a stage baseline
    (`services/baseline.py::create_baseline_for_stage`, which does the same
    transition in bulk for every draft/reviewed requirement targeting the
    stage being approved) — despite `update_requirement` already allowing a
    project manager to set `status=approved` directly via a full edit
    payload (`:578-591`). This gives that same transition its own
    single-purpose action, matching `complete`/`uncomplete` below, so the
    frontend doesn't have to resend the entire edit payload just to flip
    status.

    Gate: project manager only (C-U-03's clarification: "Project Managers
    can also provide approvals for change requests and approval of project
    requirements from scoping review to project requirements") — the same
    check `decide_change_request` and `update_requirement`'s own
    status=approved branch already use. When reached through the MCP server
    (`channel == "mcp"`), additionally requires this project and its
    organisation to both have explicitly enabled AI approval (docs/decisions.md's
    "AI approval via MCP" entry) — a plain UI/API call is unaffected by that
    flag either way.
    """
    if ProjectRole.PROJECT_MANAGER not in get_effective_project_roles(db, current_user.id, project_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only a project manager can approve a requirement.")
    requirement = db.get(Requirement, requirement_id)
    if requirement is None or requirement.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Requirement not found.")
    if channel == "mcp":
        require_ai_approvals_enabled(db, db.get(Project, project_id))
    current_version = get_current_version(db, requirement.id)
    if current_version.status not in REQUIRES_APPROVAL_STATUSES:
        raise HTTPException(status.HTTP_409_CONFLICT, "Only a draft or reviewed requirement can be approved.")
    new_version = apply_new_version(
        db, requirement, current_version, current_user,
        status_value=RequirementStatus.APPROVED,
        change_note="Approved via MCP." if channel == "mcp" else "Approved directly.",
    )
    log_event(db, entity_type="requirement", entity_id=requirement.id, action="approved",
              actor_id=current_user.id, project_id=project_id,
              detail={"via": "mcp"} if channel == "mcp" else None)
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
    """Marks an approved requirement completed (C-P-03, C-G-11), gated the
    same as archiving — a status transition a project manager can make
    directly, not content that needs to go through a change request. When
    reached through the MCP server, additionally requires this project and
    its organisation to both have explicitly enabled AI approval — see
    `approve_requirement`'s docstring.

    Sets `is_completed`/`completed_at`/`completed_by` directly on the
    `Requirement` row rather than calling `apply_new_version` — completion
    is an overlay marker independent of lifecycle state (C-G-11), not a
    change to the requirement's content, so it must not bump the version
    number the way every actual content/status edit does.
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
