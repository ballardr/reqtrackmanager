"""
Module: routers.projects.stages

Project stage lifecycle (C-G-08): create/list/rename/delete, the forward-
only status state machine (scoping -> review -> approved, C-R-05/C-G-10/
C-G-12), review-deadline scheduling and stakeholder responses, and
completion (C-P-02/C-P-03).
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models.change_request import ChangeRequestVersion
from app.models.enums import ProjectRole, StageStatus
from app.models.notification import NotificationType
from app.models.project import Project, ProjectStage, StageReviewResponse
from app.models.requirement import Baseline, RequirementVersion
from app.models.user import User
from app.schemas.project import (
    ProjectStageCreate,
    ProjectStageOut,
    ProjectStageUpdate,
    StageCompleteRequest,
    StageReviewDeadlineSet,
    StageReviewResponseCreate,
    StageReviewResponseOut,
)
from app.services.audit import log_event
from app.services.baseline import create_baseline_for_stage
from app.services.notifications import notify
from app.services.rbac import get_effective_project_roles, get_project_member_user_ids, require_project_manage, require_project_view
from app.services.stages import complete_stage

router = APIRouter(tags=["projects-stages"])


@router.post("/{project_id}/stages", response_model=ProjectStageOut, status_code=status.HTTP_201_CREATED)
def create_stage(
    payload: ProjectStageCreate,
    project: Project = Depends(require_project_manage),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Adds a new project stage (C-G-08), starting in scoping status.

    Notifies project members that a new stage has entered scoping (C-N-01)
    — this is never the "brand new project" case the requirement excludes,
    since a project's very first stage is created directly in
    `create_project`, not through this endpoint.
    """
    count = len(db.scalars(select(ProjectStage.id).where(ProjectStage.project_id == project.id)).all())
    stage = ProjectStage(project_id=project.id, name=payload.name, status=StageStatus.SCOPING, sort_order=count)
    db.add(stage)
    db.flush()
    log_event(db, entity_type="project_stage", entity_id=stage.id, action="created",
              actor_id=current_user.id, project_id=project.id)
    _notify_stage_transition(db, project, stage, current_user.id)
    db.commit()
    db.refresh(stage)
    return stage


@router.get("/{project_id}/stages", response_model=list[ProjectStageOut])
def list_stages(project_id: UUID, current_user: User = Depends(require_project_view), db: Session = Depends(get_db)):
    return db.scalars(
        select(ProjectStage).where(ProjectStage.project_id == project_id).order_by(ProjectStage.sort_order)
    ).all()


@router.patch("/{project_id}/stages/{stage_id}", response_model=ProjectStageOut)
def rename_stage(
    project_id: UUID, stage_id: UUID, payload: ProjectStageUpdate,
    project: Project = Depends(require_project_manage), current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    stage = db.get(ProjectStage, stage_id)
    if stage is None or stage.project_id != project.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Stage not found.")
    existing = db.scalar(
        select(ProjectStage.id).where(
            ProjectStage.project_id == project.id, ProjectStage.name == payload.name, ProjectStage.id != stage_id
        )
    )
    if existing is not None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A stage with this name already exists.")
    stage.name = payload.name
    log_event(db, entity_type="project_stage", entity_id=stage.id, action="renamed",
              actor_id=current_user.id, project_id=project.id)
    db.commit()
    db.refresh(stage)
    return stage


@router.delete("/{project_id}/stages/{stage_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_stage(
    project_id: UUID, stage_id: UUID, reassign_to: UUID,
    project: Project = Depends(require_project_manage), current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Deletes a stage, reassigning every requirement version and
    change-request proposal that ever targeted it to `reassign_to` first —
    `RequirementVersion.target_stage_id` is mandatory (never null), so this
    isn't optional the way unlinking a file is.

    Refuses to delete a stage any approved baseline snapshots (C-G-10):
    a `Baseline` is documented as an *immutable* record of what a specific
    stage's approved requirements looked like, and silently repointing it
    at a different stage would quietly rewrite what that snapshot means.
    Archiving/renaming is always available instead; only a stage with no
    baseline history can be removed outright. `reassign_to` must be a
    different, existing stage in the same project — if this is the
    project's only stage, no valid target exists and deletion is refused
    (a project must always have at least one stage).
    """
    stage = db.get(ProjectStage, stage_id)
    if stage is None or stage.project_id != project.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Stage not found.")
    if reassign_to == stage_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "reassign_to must be a different stage.")
    target = db.get(ProjectStage, reassign_to)
    if target is None or target.project_id != project.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "reassign_to must be an existing stage in this project.")
    has_baseline = db.scalar(select(Baseline.id).where(Baseline.stage_id == stage_id)) is not None
    if has_baseline:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This stage has an approved baseline and can't be deleted — baselines are immutable history.",
        )
    db.execute(
        RequirementVersion.__table__.update()
        .where(RequirementVersion.target_stage_id == stage_id)
        .values(target_stage_id=reassign_to)
    )
    db.execute(
        ChangeRequestVersion.__table__.update()
        .where(ChangeRequestVersion.proposed_target_stage_id == stage_id)
        .values(proposed_target_stage_id=reassign_to)
    )
    if stage.is_current:
        target.is_current = True
    log_event(db, entity_type="project_stage", entity_id=stage_id, action="deleted",
              actor_id=current_user.id, project_id=project.id, detail={"reassigned_to": str(reassign_to)})
    db.delete(stage)
    db.commit()


#: Explicit forward-only lifecycle transitions this endpoint permits, keyed
#: by the stage's *current* status. COMPLETED is deliberately absent as a
#: value here — it's only reachable via the dedicated `/stages/{id}/complete`
#: endpoint (C-P-02), which also handles the `cascade_to_requirements` flag
#: and doesn't belong in a generic status-setter. ARCHIVED is reachable from
#: any non-terminal status, matching its own documented purpose as a manual,
#: no-special-gating display/filtering state (see `StageStatus`'s docstring).
_ALLOWED_STAGE_TRANSITIONS: dict[StageStatus, set[StageStatus]] = {
    StageStatus.SCOPING: {StageStatus.REVIEW, StageStatus.ARCHIVED},
    StageStatus.REVIEW: {StageStatus.APPROVED, StageStatus.ARCHIVED},
    StageStatus.APPROVED: {StageStatus.ARCHIVED},
}


@router.post("/{project_id}/stages/{stage_id}/transition", response_model=ProjectStageOut)
def transition_stage(
    project_id: UUID,
    stage_id: UUID,
    new_status: StageStatus,
    project: Project = Depends(require_project_manage),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Transitions a stage's lifecycle status.

    Approving a stage (-> APPROVED) writes an immutable baseline (C-G-10)
    and, from that point on, locks direct requirement edits project-wide
    until further change requests are approved (C-G-12). This transition
    requires the project manager role specifically (C-U-03 clarification),
    not just general settings-management access.

    Only the forward transitions in `_ALLOWED_STAGE_TRANSITIONS` are
    accepted (plus the always-available move to ARCHIVED) — a stage can't
    skip a step (e.g. straight from SCOPING to APPROVED, bypassing the
    review-deadline/stakeholder-response workflow, C-R-05) or move
    backwards (e.g. APPROVED back to SCOPING, which would silently unlock
    already-locked requirements outside the change-request process,
    C-G-12). COMPLETED is intentionally not settable here at all; see
    `/stages/{stage_id}/complete`.
    """
    stage = db.get(ProjectStage, stage_id)
    if stage is None or stage.project_id != project.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Stage not found.")

    # Role check before state-machine check for APPROVED specifically, so an
    # unauthorized caller always gets a uniform 403 rather than a 409 that
    # would leak the stage's current status to someone who can't act on it
    # anyway (matches C-U-03's PM-only approval gate being checked first
    # everywhere else in this file).
    if new_status == StageStatus.APPROVED:
        if ProjectRole.PROJECT_MANAGER not in get_effective_project_roles(db, current_user.id, project.id):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Only a project manager can approve a stage.")

    allowed = _ALLOWED_STAGE_TRANSITIONS.get(stage.status, set())
    if new_status not in allowed:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Cannot transition a stage from '{stage.status.value}' to '{new_status.value}'.",
        )

    if new_status == StageStatus.APPROVED:
        stage.status = StageStatus.APPROVED
        stage.approved_at = datetime.now(UTC)
        stage.approved_by = current_user.id
        create_baseline_for_stage(db, project, stage, current_user)
        log_event(db, entity_type="project_stage", entity_id=stage.id, action="approved",
                   actor_id=current_user.id, project_id=project.id)
    else:
        stage.status = new_status
        log_event(db, entity_type="project_stage", entity_id=stage.id, action="status_changed",
                   actor_id=current_user.id, project_id=project.id, detail={"status": new_status.value})

    _notify_stage_transition(db, project, stage, current_user.id)
    db.commit()
    db.refresh(stage)
    return stage


@router.post("/{project_id}/stages/{stage_id}/review-deadline", response_model=ProjectStageOut)
def set_stage_review_deadline(
    project_id: UUID, stage_id: UUID, payload: StageReviewDeadlineSet,
    project: Project = Depends(require_project_manage), current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Sets (or clears) a stage's review-response deadline (C-R-05).

    Only meaningful while the stage is in REVIEW; the daily scheduler sweep
    (services/stages.py) auto-approves the stage once the deadline passes
    with no stakeholder rejection. Setting a new deadline clears any
    responses from a prior review cycle so they don't leak into this one.
    """
    stage = db.get(ProjectStage, stage_id)
    if stage is None or stage.project_id != project.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Stage not found.")
    if stage.status != StageStatus.REVIEW:
        raise HTTPException(status.HTTP_409_CONFLICT, "A review deadline can only be set while the stage is in review.")
    db.execute(StageReviewResponse.__table__.delete().where(StageReviewResponse.stage_id == stage.id))
    stage.review_deadline = payload.review_deadline
    log_event(db, entity_type="project_stage", entity_id=stage.id, action="review_deadline_set",
              actor_id=current_user.id, project_id=project.id,
              detail={"review_deadline": payload.review_deadline.isoformat() if payload.review_deadline else None})
    db.commit()
    db.refresh(stage)
    return stage


@router.post("/{project_id}/stages/{stage_id}/review-response", response_model=StageReviewResponseOut)
def submit_stage_review_response(
    project_id: UUID, stage_id: UUID, payload: StageReviewResponseCreate,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    """A stakeholder's response to a stage's review deadline (C-R-05)."""
    stage = db.get(ProjectStage, stage_id)
    if stage is None or stage.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Stage not found.")
    if stage.status != StageStatus.REVIEW or stage.review_deadline is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "This stage has no open review deadline.")
    if ProjectRole.STAKEHOLDER not in get_effective_project_roles(db, current_user.id, project_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only stakeholders or managers may respond to a stage review.")

    existing = db.scalar(
        select(StageReviewResponse).where(StageReviewResponse.stage_id == stage.id, StageReviewResponse.user_id == current_user.id)
    )
    if existing is not None:
        existing.response = payload.response
        existing.comment = payload.comment
        existing.responded_at = datetime.now(UTC)
        response = existing
    else:
        response = StageReviewResponse(
            stage_id=stage.id, user_id=current_user.id, response=payload.response,
            comment=payload.comment, responded_at=datetime.now(UTC),
        )
        db.add(response)
    db.commit()
    db.refresh(response)
    return response


@router.post("/{project_id}/stages/{stage_id}/complete", response_model=ProjectStageOut)
def complete_stage_endpoint(
    project_id: UUID, stage_id: UUID, payload: StageCompleteRequest,
    project: Project = Depends(require_project_manage), current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Marks a stage completed (C-P-02), optionally cascading to its
    approved requirements (C-P-03, defaults to off per the requirement's
    clarification)."""
    stage = db.get(ProjectStage, stage_id)
    if stage is None or stage.project_id != project.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Stage not found.")
    complete_stage(db, project, stage, current_user, cascade_to_requirements=payload.cascade_to_requirements)
    db.commit()
    db.refresh(stage)
    return stage


_STAGE_NOTIFICATION_TYPES = {
    StageStatus.SCOPING: NotificationType.STAGE_SCOPING,
    StageStatus.REVIEW: NotificationType.STAGE_REVIEW,
    StageStatus.APPROVED: NotificationType.STAGE_APPROVED,
    StageStatus.COMPLETED: NotificationType.STAGE_COMPLETED,
}


def _notify_stage_transition(db: Session, project: Project, stage: ProjectStage, actor_id: UUID) -> None:
    """Notifies all project members of stage transitions (C-N-01), including
    a newly created stage entering scoping.

    Per the requirement's "unless brand new project" clarification, a brand
    new *project's* very first stage must not notify — but that stage is
    created directly in `create_project` (never through this function), so
    every actual caller of `_notify_stage_transition` (a subsequent stage
    being created via `create_stage`, or an existing stage transitioning via
    `transition_stage`) is, by construction, never that excluded case.

    `actor_id` is whoever created the stage or triggered the transition —
    excluded from this broadcast so they're not told about the very change
    they just made (e.g. the project manager who approved the stage).
    """
    notification_type = _STAGE_NOTIFICATION_TYPES.get(stage.status)
    if notification_type is None:
        return
    member_ids = get_project_member_user_ids(db, project.id)
    for user_id in member_ids:
        user = db.get(User, user_id)
        if user is not None:
            notify(
                db, user, notification_type=notification_type,
                title=f"{project.name}: {stage.name} is now {stage.status.value}",
                project_id=project.id, entity_type="project_stage", entity_id=str(stage.id),
                actor_id=actor_id,
            )
