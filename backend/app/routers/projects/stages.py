"""
Module: routers.projects.stages

Project stage lifecycle (C-G-08): create/list/rename/delete, movement between
the phases of the stage's workflow (`services.stage_workflows`; entering a
locked phase baselines and locks, C-R-05/C-G-10/C-G-12; entering a closed one
completes the stage, C-P-02/C-P-03), and review-deadline scheduling and
stakeholder responses.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models.change_request import ChangeRequestVersion
from app.models.enums import ProjectRole, StagePhaseKind
from app.models.notification import NotificationType
from app.models.project import Project, ProjectStage, StageReviewResponse
from app.models.requirement import Baseline, RequirementVersion
from app.models.stage_workflow import StageWorkflow, StageWorkflowPhase
from app.models.user import User
from app.schemas.project import (
    ProjectStageCreate,
    ProjectStageOut,
    ProjectStageUpdate,
    StageReviewDeadlineSet,
    StageReviewResponseCreate,
    StageReviewResponseOut,
)
from app.schemas.stage_workflow import StageTransitionRequest
from app.services.audit import log_event
from app.services.notifications import notify
from app.services.principals import principal_columns, principal_labels, principal_ref, validate_principal
from app.services.rbac import get_effective_project_roles, get_project_member_user_ids, require_project_manage, require_project_view
from app.services.stage_workflows import (
    WorkflowConflict,
    default_workflow,
    effective_workflows,
    move_stage,
    new_stage,
    phase_index,
    phase_kind_of,
    start_phase,
)

router = APIRouter(tags=["projects-stages"])


def _stages_out(db: Session, stages: list[ProjectStage], viewer: User | None = None) -> list[ProjectStageOut]:
    """Stage responses with each stage's workflow and phase names, read in two queries.

    With a `viewer`, each carries whether that person may enter or leave a locked phase (`can_lock`).
    """
    can_lock = bool(
        viewer is not None and stages
        and ProjectRole.PROJECT_MANAGER in get_effective_project_roles(db, viewer.id, stages[0].project_id)
    )
    phases = phase_index(db, {s.phase_id for s in stages})
    workflow_ids = {s.workflow_id for s in stages}
    workflows = {
        w.id: w.name for w in db.scalars(select(StageWorkflow).where(StageWorkflow.id.in_(workflow_ids))).all()
    } if workflow_ids else {}
    labels = principal_labels(db, [principal_ref(s.owner_type, s.owner_id) for s in stages])
    out = []
    for stage in stages:
        phase = phases[stage.phase_id]
        owner_ref = principal_ref(stage.owner_type, stage.owner_id)
        out.append(ProjectStageOut(
            id=stage.id, project_id=stage.project_id, name=stage.name, workflow_id=stage.workflow_id,
            workflow_name=workflows.get(stage.workflow_id, ""), phase_id=phase.id, phase_name=phase.name,
            phase_kind=phase.kind, sort_order=stage.sort_order, is_current=stage.is_current,
            approved_at=stage.approved_at, completed_at=stage.completed_at, completed_by=stage.completed_by,
            review_deadline=stage.review_deadline, can_lock=can_lock,
            owner=labels.get((owner_ref.type.value, owner_ref.id)) if owner_ref is not None else None,
        ))
    return out


def _stage_out(db: Session, stage: ProjectStage, viewer: User | None = None) -> ProjectStageOut:
    return _stages_out(db, [stage], viewer)[0]


def _get_stage(db: Session, project: Project, stage_id: UUID) -> ProjectStage:
    stage = db.get(ProjectStage, stage_id)
    if stage is None or stage.project_id != project.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Stage not found.")
    return stage


def _usable_workflow(db: Session, project: Project, workflow_id: UUID) -> StageWorkflow:
    """The workflow if the project may use it (effective set), else a 400."""
    for workflow in effective_workflows(db, project):
        if workflow.id == workflow_id:
            return workflow
    raise HTTPException(status.HTTP_400_BAD_REQUEST, "workflow_id must be a workflow available to this project.")


@router.post("/{project_id}/stages", response_model=ProjectStageOut, status_code=status.HTTP_201_CREATED)
def create_stage(
    payload: ProjectStageCreate,
    project: Project = Depends(require_project_manage),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Adds a new project stage (C-G-08), at the starting phase of the chosen
    workflow (default: the project's default workflow).

    Notifies project members that a new stage has entered its starting phase (C-N-01)
    — this is never the "brand new project" case the requirement excludes,
    since a project's very first stage is created directly in
    `create_project`, not through this endpoint.
    """
    count = len(db.scalars(select(ProjectStage.id).where(ProjectStage.project_id == project.id)).all())
    workflow = _usable_workflow(db, project, payload.workflow_id) if payload.workflow_id else default_workflow(db, project)
    stage = new_stage(db, project, payload.name, count, workflow=workflow)
    log_event(db, entity_type="project_stage", entity_id=stage.id, action="created",
              actor_id=current_user.id, project_id=project.id)
    _notify_stage_transition(db, project, stage, current_user.id)
    db.commit()
    db.refresh(stage)
    return _stage_out(db, stage)


@router.get("/{project_id}/stages", response_model=list[ProjectStageOut])
def list_stages(project_id: UUID, current_user: User = Depends(require_project_view), db: Session = Depends(get_db)):
    return _stages_out(db, list(db.scalars(
        select(ProjectStage).where(ProjectStage.project_id == project_id).order_by(ProjectStage.sort_order)
    ).all()), current_user)


@router.patch("/{project_id}/stages/{stage_id}", response_model=ProjectStageOut)
def rename_stage(
    project_id: UUID, stage_id: UUID, payload: ProjectStageUpdate,
    project: Project = Depends(require_project_manage), current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Renames a stage and, optionally, moves it to the start of another workflow or changes its owner.

    A workflow change is refused unless the stage is still in an open phase with no baseline: moving a
    locked or closed stage to another workflow's start would unlock it outside the change-request process.
    """
    stage = _get_stage(db, project, stage_id)
    existing = db.scalar(
        select(ProjectStage.id).where(
            ProjectStage.project_id == project.id, ProjectStage.name == payload.name, ProjectStage.id != stage_id
        )
    )
    if existing is not None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A stage with this name already exists.")
    stage.name = payload.name
    if payload.workflow_id is not None and payload.workflow_id != stage.workflow_id:
        workflow = _usable_workflow(db, project, payload.workflow_id)
        has_baseline = db.scalar(select(Baseline.id).where(Baseline.stage_id == stage.id)) is not None
        if has_baseline or phase_kind_of(db, stage) != StagePhaseKind.OPEN:
            raise HTTPException(
                status.HTTP_409_CONFLICT, "A stage can change workflow only while it is in an open phase and has no baseline."
            )
        stage.workflow_id = workflow.id
        stage.phase_id = start_phase(db, workflow.id).id
        log_event(db, entity_type="project_stage", entity_id=stage.id, action="workflow_changed",
                  actor_id=current_user.id, project_id=project.id, detail={"workflow": workflow.name})
    if "owner" in payload.model_fields_set:
        validate_principal(db, payload.owner, organization_id=project.organization_id, project_id=project.id, field="owner")
        for key, value in principal_columns("owner", payload.owner).items():
            setattr(stage, key, value)
        log_event(db, entity_type="project_stage", entity_id=stage.id, action="owner_changed", actor_id=current_user.id,
                  project_id=project.id, detail={"owner_type": payload.owner.type.value if payload.owner else None,
                                                 "owner_id": str(payload.owner.id) if payload.owner else None})
    log_event(db, entity_type="project_stage", entity_id=stage.id, action="renamed",
              actor_id=current_user.id, project_id=project.id)
    db.commit()
    db.refresh(stage)
    return _stage_out(db, stage)


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
        update(RequirementVersion)
        .where(RequirementVersion.target_stage_id == stage_id)
        .values(target_stage_id=reassign_to)
    )
    db.execute(
        update(ChangeRequestVersion)
        .where(ChangeRequestVersion.proposed_target_stage_id == stage_id)
        .values(proposed_target_stage_id=reassign_to)
    )
    if stage.is_current:
        target.is_current = True
    log_event(db, entity_type="project_stage", entity_id=stage_id, action="deleted",
              actor_id=current_user.id, project_id=project.id, detail={"reassigned_to": str(reassign_to)})
    db.delete(stage)
    db.commit()


@router.post("/{project_id}/stages/{stage_id}/transition", response_model=ProjectStageOut)
def transition_stage(
    project_id: UUID,
    stage_id: UUID,
    payload: StageTransitionRequest,
    project: Project = Depends(require_project_manage),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Moves a stage to another phase of its own workflow.

    Moves are free in either direction; the phase kind decides what happens
    (`services.stage_workflows.move_stage`). Entering a locked phase writes an
    immutable baseline (C-G-10), from which direct requirement edits are limited
    to change requests (C-G-12); entering a closed phase completes the stage
    (C-P-02) and, with `cascade_to_requirements`, its approved requirements
    (C-P-03). Entering or leaving a locked phase requires the project manager
    role (C-U-03 clarification), checked before the state so an unauthorised
    caller always gets a uniform 403 rather than a 409 that would leak the
    stage's current phase.
    """
    stage = _get_stage(db, project, stage_id)
    phase = db.get(StageWorkflowPhase, payload.phase_id)
    if phase is None or phase.workflow_id != stage.workflow_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "phase_id must be a phase of the stage's workflow.")
    try:
        move_stage(
            db, project, stage, phase, current_user,
            actor_roles=get_effective_project_roles(db, current_user.id, project.id),
            cascade_to_requirements=payload.cascade_to_requirements,
        )
    except PermissionError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc
    except WorkflowConflict as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    _notify_stage_transition(db, project, stage, current_user.id)
    db.commit()
    db.refresh(stage)
    return _stage_out(db, stage)


@router.post("/{project_id}/stages/{stage_id}/review-deadline", response_model=ProjectStageOut)
def set_stage_review_deadline(
    project_id: UUID, stage_id: UUID, payload: StageReviewDeadlineSet,
    project: Project = Depends(require_project_manage), current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Sets (or clears) a stage's review-response deadline (C-R-05).

    Only meaningful while the stage is in a review phase; the daily scheduler sweep
    (services/stages.py) auto-approves the stage once the deadline passes
    with no stakeholder rejection. Setting a new deadline clears any
    responses from a prior review cycle so they don't leak into this one.
    """
    stage = _get_stage(db, project, stage_id)
    if phase_kind_of(db, stage) != StagePhaseKind.REVIEW:
        raise HTTPException(status.HTTP_409_CONFLICT, "A review deadline can only be set while the stage is in a review phase.")
    db.execute(delete(StageReviewResponse).where(StageReviewResponse.stage_id == stage.id))
    stage.review_deadline = payload.review_deadline
    log_event(db, entity_type="project_stage", entity_id=stage.id, action="review_deadline_set",
              actor_id=current_user.id, project_id=project.id,
              detail={"review_deadline": payload.review_deadline.isoformat() if payload.review_deadline else None})
    db.commit()
    db.refresh(stage)
    return _stage_out(db, stage)


@router.post("/{project_id}/stages/{stage_id}/review-response", response_model=StageReviewResponseOut)
def submit_stage_review_response(
    project_id: UUID, stage_id: UUID, payload: StageReviewResponseCreate,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    """A stakeholder's response to a stage's review deadline (C-R-05)."""
    stage = db.get(ProjectStage, stage_id)
    if stage is None or stage.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Stage not found.")
    if phase_kind_of(db, stage) != StagePhaseKind.REVIEW or stage.review_deadline is None:
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
    log_event(
        db, entity_type="project_stage", entity_id=stage.id, action="review_response_submitted",
        actor_id=current_user.id, project_id=project_id, detail={"response": str(getattr(payload.response, "value", payload.response))},
    )
    db.commit()
    db.refresh(response)
    return response


#: A phase kind's notification; a paused or archived phase announces nothing.
_STAGE_NOTIFICATION_TYPES = {
    StagePhaseKind.OPEN: NotificationType.STAGE_SCOPING,
    StagePhaseKind.REVIEW: NotificationType.STAGE_REVIEW,
    StagePhaseKind.LOCKED: NotificationType.STAGE_APPROVED,
    StagePhaseKind.CLOSED: NotificationType.STAGE_COMPLETED,
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
    phase = db.get(StageWorkflowPhase, stage.phase_id)
    notification_type = _STAGE_NOTIFICATION_TYPES.get(phase.kind) if phase is not None else None
    if phase is None or notification_type is None:
        return
    member_ids = get_project_member_user_ids(db, project.id)
    for user_id in member_ids:
        user = db.get(User, user_id)
        if user is not None:
            notify(
                db, user, notification_type=notification_type,
                title=f"{project.name}: {stage.name} is now {phase.name}",
                project_id=project.id, entity_type="project_stage", entity_id=str(stage.id),
                actor_id=actor_id,
            )
