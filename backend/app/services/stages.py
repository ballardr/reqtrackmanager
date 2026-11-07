"""
Module: services.stages

Project stage business logic added for Massif (v3): the review-deadline
"assumed approval" sweep (C-R-05) and completion tracking (C-P-02).
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import ProjectRole, RequirementStatus, StagePhaseKind, StageReviewResponseChoice
from app.models.notification import NotificationType
from app.models.project import Project, ProjectStage, StageReviewResponse
from app.models.requirement import Requirement, RequirementVersion
from app.models.stage_workflow import ComponentStageState, StageWorkflowPhase
from app.models.user import User
from app.services.audit import log_event
from app.services.component_stages import tracked_component_ids
from app.services.lookups import project_or_404
from app.services.notifications import notify
from app.services.rbac import get_effective_project_managers, get_project_member_user_ids
from app.services.stage_workflows import first_phase_of_kind, move_stage, phases_of


def auto_approve_overdue_stage_reviews(db: Session) -> None:
    """Daily sweep (C-R-05): for every stage in a review phase whose
    `review_deadline` has passed, moves it to the workflow's next locked phase
    unless a stakeholder explicitly rejected — "if they have not provided a
    response, then it's assumed they have approved the requirements." An
    explicit rejection blocks the auto-approval so a raised objection is never
    silently overridden; the stage is left in review for a project manager to
    resolve manually. A workflow with no locked phase has nothing to approve
    into, so its stages are left alone.
    """
    now = datetime.now(UTC)
    overdue_stages = db.scalars(
        select(ProjectStage)
        .join(StageWorkflowPhase, StageWorkflowPhase.id == ProjectStage.phase_id)
        .where(
            StageWorkflowPhase.kind == StagePhaseKind.REVIEW,
            ProjectStage.review_deadline.is_not(None),
            ProjectStage.review_deadline <= now,
        )
    ).all()

    for stage in overdue_stages:
        has_rejection = db.scalar(
            select(StageReviewResponse.id).where(
                StageReviewResponse.stage_id == stage.id,
                StageReviewResponse.response == StageReviewResponseChoice.REJECTED,
            )
        )
        if has_rejection is not None:
            continue

        project = project_or_404(db, stage.project_id)
        manager_ids = get_effective_project_managers(db, project.id)
        if not manager_ids:
            continue
        actor = db.get(User, min(manager_ids))
        if actor is None:
            continue

        phases = phases_of(db, stage.workflow_id)
        current = next((p for p in phases if p.id == stage.phase_id), None)
        target = first_phase_of_kind(phases, StagePhaseKind.LOCKED, current.sort_order if current else -1)
        if target is None:
            continue
        move_stage(
            db, project, stage, target, actor, actor_roles={ProjectRole.PROJECT_MANAGER},
            reason="review_deadline_passed_no_rejection",
        )
        for user_id in get_project_member_user_ids(db, project.id):
            member = db.get(User, user_id)
            if member is not None:
                notify(
                    db, member, notification_type=NotificationType.STAGE_REVIEW_AUTO_APPROVED,
                    title=f"{project.name}: {stage.name}'s review deadline passed with no objections — moved to {target.name}",
                    project_id=project.id, entity_type="project_stage", entity_id=str(stage.id),
                )

    db.commit()


def complete_stage(
    db: Session, project: Project, stage: ProjectStage, actor: User, *, cascade_to_requirements: bool,
    holder: ProjectStage | ComponentStageState | None = None, component_id: UUID | None = None,
) -> None:
    """Records a stage's completion (C-P-02), logging who/when; the caller has already moved it
    into a closed phase (`stage_workflows.apply_phase_move`).

    Args:
        holder: What completed: the stage itself (default) or one component's state within it.
        component_id: Set for a component state; the cascade then reaches only that component's requirements.
        cascade_to_requirements: If True, also marks every approved
            requirement targeting this stage as completed (C-P-03). Defaults
            to False at the API layer per the requirement's clarification.
    """
    now = datetime.now(UTC)
    target = holder if holder is not None else stage
    target.completed_at = now
    target.completed_by = actor.id
    entity_type, entity_id = ("project_stage", stage.id) if target is stage else ("component_stage_state", target.id)
    log_event(db, entity_type=entity_type, entity_id=entity_id, action="completed", actor_id=actor.id, project_id=project.id)

    if cascade_to_requirements:
        query = (
            select(Requirement)
            .join(RequirementVersion, RequirementVersion.requirement_id == Requirement.id)
            .where(
                Requirement.project_id == project.id,
                Requirement.is_archived.is_(False),
                Requirement.is_completed.is_(False),
                RequirementVersion.valid_to.is_(None),
                RequirementVersion.target_stage_id == stage.id,
                RequirementVersion.status == RequirementStatus.APPROVED,
            )
        )
        if component_id is not None:
            query = query.where(Requirement.component_id == component_id)
        elif tracked := tracked_component_ids(db, project, stage):
            query = query.where(Requirement.component_id.not_in(tracked))
        targeting = db.scalars(query).all()
        # Sets the completion overlay directly (C-G-11), same as
        # `routers.requirements.complete_requirement` — cascading a stage
        # completion doesn't change any requirement's content, so this must
        # not create a new `RequirementVersion` for each one either.
        for requirement in targeting:
            requirement.is_completed = True
            requirement.completed_at = now
            requirement.completed_by = actor.id
