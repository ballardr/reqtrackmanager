"""
Module: services.stages

Project stage business logic added for Massif (v3): the review-deadline
"assumed approval" sweep (C-R-05) and completion tracking (C-P-02).
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import RequirementStatus, StageReviewResponseChoice, StageStatus
from app.models.notification import NotificationType
from app.models.project import Project, ProjectStage, StageReviewResponse
from app.models.requirement import Requirement, RequirementVersion
from app.models.user import User
from app.services.audit import log_event
from app.services.baseline import create_baseline_for_stage
from app.services.notifications import notify
from app.services.rbac import get_effective_project_managers, get_project_member_user_ids


def auto_approve_overdue_stage_reviews(db: Session) -> None:
    """Daily sweep (C-R-05): for every stage still in REVIEW whose
    `review_deadline` has passed, auto-approves it unless a stakeholder
    explicitly rejected — "if they have not provided a response, then it's
    assumed they have approved the requirements." An explicit rejection
    blocks the auto-approval so a raised objection is never silently
    overridden; the stage is left in REVIEW for a project manager to
    resolve manually.
    """
    now = datetime.now(UTC)
    overdue_stages = db.scalars(
        select(ProjectStage).where(
            ProjectStage.status == StageStatus.REVIEW,
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

        project = db.get(Project, stage.project_id)
        manager_ids = get_effective_project_managers(db, project.id)
        if not manager_ids:
            continue
        actor = db.get(User, min(manager_ids))
        if actor is None:
            continue

        stage.status = StageStatus.APPROVED
        stage.approved_at = now
        stage.approved_by = actor.id
        create_baseline_for_stage(db, project, stage, actor)
        log_event(
            db, entity_type="project_stage", entity_id=stage.id, action="approved", actor_id=actor.id,
            project_id=project.id, detail={"reason": "review_deadline_passed_no_rejection"},
        )
        for user_id in get_project_member_user_ids(db, project.id):
            member = db.get(User, user_id)
            if member is not None:
                notify(
                    db, member, notification_type=NotificationType.STAGE_REVIEW_AUTO_APPROVED,
                    title=f"{project.name}: {stage.name}'s review deadline passed with no objections — approved",
                    project_id=project.id, entity_type="project_stage", entity_id=str(stage.id),
                )

    db.commit()


def complete_stage(db: Session, project: Project, stage: ProjectStage, actor: User, *, cascade_to_requirements: bool) -> None:
    """Marks a stage completed (C-P-02), logging who/when.

    Args:
        cascade_to_requirements: If True, also marks every approved
            requirement targeting this stage as completed (C-P-03). Defaults
            to False at the API layer per the requirement's clarification.
    """
    now = datetime.now(UTC)
    stage.status = StageStatus.COMPLETED
    stage.completed_at = now
    stage.completed_by = actor.id
    log_event(db, entity_type="project_stage", entity_id=stage.id, action="completed", actor_id=actor.id, project_id=project.id)

    if cascade_to_requirements:
        targeting = db.scalars(
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
        ).all()
        # Sets the completion overlay directly (C-G-11), same as
        # `routers.requirements.complete_requirement` — cascading a stage
        # completion doesn't change any requirement's content, so this must
        # not create a new `RequirementVersion` for each one either.
        for requirement in targeting:
            requirement.is_completed = True
            requirement.completed_at = now
            requirement.completed_by = actor.id
