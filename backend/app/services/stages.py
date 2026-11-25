"""
Module: services.stages

Project stage business logic added for Massif (v3): the review-deadline
"assumed approval" sweep (C-R-05) and completion tracking (C-P-02).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import ProjectRole, RequirementStatus, StagePhaseKind, StageReviewResponseChoice
from app.models.notification import Notification, NotificationType
from app.models.project import Project, ProjectStage, StageReviewResponse
from app.models.requirement import Requirement, RequirementVersion
from app.models.stage_workflow import ComponentStageState, StageWorkflowPhase
from app.models.user import User
from app.modules.seams import BaselinePolicy, GovernanceSeam
from app.services import governance_seams
from app.services.audit import log_event
from app.services.baseline import BaselineRefused
from app.services.codes import qualify
from app.services.component_stages import tracked_component_ids
from app.services.lookups import project_or_404
from app.services.notifications import notify
from app.services.rbac import get_effective_project_managers, get_project_member_user_ids
from app.services.stage_workflows import first_phase_of_kind, move_stage, phases_of

logger = logging.getLogger(__name__)


def auto_approve_overdue_stage_reviews(db: Session) -> None:
    """Daily sweep (C-R-05): for every stage in a review phase whose
    `review_deadline` has passed, moves it to the workflow's next locked phase
    unless a stakeholder explicitly rejected — "if they have not provided a
    response, then it's assumed they have approved the requirements." An
    explicit rejection blocks the auto-approval so a raised objection is never
    silently overridden; the stage is left in review for a project manager to
    resolve manually. A workflow with no locked phase has nothing to approve
    into, so its stages are left alone. A stage whose move is refused by a check of the project's baseline policy
    (`services.baseline.BaselineRefused`) is left in review with nothing approved, retried by the next sweep, and its
    project managers are told once for each distinct set of failures (`_notify_baseline_refused`).
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
        try:
            with db.begin_nested():
                move_stage(
                    db, project, stage, target, actor, actor_roles={ProjectRole.PROJECT_MANAGER},
                    reason="review_deadline_passed_no_rejection",
                )
        except BaselineRefused as refused:
            if _managers_are_notified(db, project):
                _notify_baseline_refused(db, project, stage, target, refused, manager_ids)
            continue
        except HTTPException as refusal:
            # The approval rules (such as a separate approver) refuse the acting manager for one stage; the others still run.
            logger.warning("Automatic approval of stage %s was refused: %s", stage.id, refusal.detail)
            continue
        for user_id in get_project_member_user_ids(db, project.id):
            member = db.get(User, user_id)
            if member is not None:
                notify(
                    db, member, notification_type=NotificationType.STAGE_REVIEW_AUTO_APPROVED,
                    title=f"{project.name}: {stage.name}'s review deadline passed with no objections — moved to {target.name}",
                    project_id=project.id, entity_type="project_stage", entity_id=str(stage.id),
                )

    db.commit()


def _managers_are_notified(db: Session, project: Project) -> bool:
    """Whether the project's baseline policy asks for managers to be told of a refused automatic approval.

    Args:
        db: An active database session.
        project: The project.

    Returns:
        The policy's `notify_managers`; true when no policy answers the baseline seam.
    """
    policy = governance_seams.resolve_project_policy(db, project.id, GovernanceSeam.BASELINE)
    return not isinstance(policy, BaselinePolicy) or policy.notify_managers


def _notify_baseline_refused(
    db: Session, project: Project, stage: ProjectStage, target: StageWorkflowPhase, refused: BaselineRefused,
    manager_ids: set[UUID],
) -> None:
    """Tells a project's managers that the automatic approval of `stage` was refused by a baseline check.

    The notice is sent once for each distinct set of failures: when the stage already has a notice of this type with the
    same text, the daily retry stays silent, and a changed set of failures notifies again. Each manager's own
    notification preference for the type applies on top of the policy's `notify_managers`. Flushed, not committed.

    Args:
        db: An active database session.
        project: The project.
        stage: The stage that stays in review.
        target: The locked phase it was to enter.
        refused: The refusal, whose failures name records by code and carry no personal data.
        manager_ids: The project's managers.
    """
    shown = refused.failures[:10]
    lines = [f"{qualify(project.code, f.code) if f.code else f.artefact_type}: {f.message} ({f.check_name})" for f in shown]
    if len(refused.failures) > len(shown):
        lines.append(f"{len(refused.failures) - len(shown)} further failures are not listed.")
    body = "\n".join([str(refused), *lines])
    already = db.scalar(
        select(Notification.id).where(
            Notification.type == NotificationType.STAGE_BASELINE_REFUSED.value,
            Notification.entity_id == str(stage.id), Notification.body == body,
        ).limit(1)
    )
    if already is not None:
        return
    for user_id in sorted(manager_ids):
        manager = db.get(User, user_id)
        if manager is not None:
            notify(
                db, manager, notification_type=NotificationType.STAGE_BASELINE_REFUSED,
                title=f"{project.name}: {stage.name} stays in review, a baseline check failed before {target.name}",
                body=body, project_id=project.id, entity_type="project_stage", entity_id=str(stage.id),
            )
    db.flush()


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
        # Sets the completion overlay directly (C-G-11), as `routers.requirements.complete_requirement` does: a
        # cascaded stage completion changes no content, so it creates no `RequirementVersion`.
        for requirement in targeting:
            requirement.is_completed = True
            requirement.completed_at = now
            requirement.completed_by = actor.id
