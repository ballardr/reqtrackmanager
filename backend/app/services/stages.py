"""
Module: services.stages

Project stage business logic added for Massif (v3): the review-deadline
"assumed approval" sweep (C-R-05) and completion tracking (C-P-02).

Responsibilities:
- `auto_approve_overdue_stage_reviews`: the daily action that approves a stage in review whose deadline passed.
- `STAGE_REVIEW_ADAPTER`: the review engine's reading of a stage's review deadline (type `stage_review`), so the
  stakeholders who have not responded, and the managers, are reminded once before the deadline.
- `complete_stage`: completion tracking.

Design decisions:
- The auto-approval is an action and stays here; the reminder before it belongs to the review engine, so the review
  policy's lead and default owner apply to it.
- A deadline is an instant; the reminder's due date is its UTC date, because the reminder has no person whose day it could
  use. A deadline that has already passed is not reminded: the auto-approval acts on it.
- Those reminded are the project's stakeholders who have not responded to the stage (the role that may respond; the
  review notification itself goes to every member), plus the project managers, or the review policy's default owner in
  their place. A stakeholder who rejected has responded and is not reminded; the managers still are.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import UTC, date, datetime
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.models.enums import ProjectRole, RequirementStatus, StagePhaseKind, StageReviewResponseChoice
from app.models.notification import Notification, NotificationType
from app.models.project import Project, ProjectStage, StageReviewResponse
from app.models.requirement import Requirement, RequirementVersion
from app.models.stage_workflow import ComponentStageState, StageWorkflowPhase
from app.models.user import User
from app.modules.seams import BaselinePolicy, DueReview, GovernanceSeam, ReminderMark, ReviewAdapter, ReviewReminder
from app.services import governance_seams
from app.services.audit import log_event
from app.services.baseline import BaselineRefused
from app.services.codes import qualify
from app.services.component_stages import tracked_component_ids
from app.services.lookups import project_or_404
from app.services.notifications import notify
from app.services.rbac import get_effective_project_managers, get_project_member_user_ids, get_project_users_by_role
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


# --- the review engine's adapter for a stage's review deadline -------------------------------------------


def _deadline_stages(db: Session, *where: ColumnElement[bool]) -> list[ProjectStage]:
    """Stages in a review phase that have a deadline, narrowed by `where`."""
    return list(db.scalars(
        select(ProjectStage).join(StageWorkflowPhase, StageWorkflowPhase.id == ProjectStage.phase_id)
        .where(StageWorkflowPhase.kind == StagePhaseKind.REVIEW, ProjectStage.review_deadline.is_not(None), *where)
    ).all())


def _stage_review_due(db: Session, project_id: UUID, as_of: date) -> list[DueReview]:
    """The project's stages in review whose deadline falls on or before `as_of` (UTC date), earliest first."""
    stages = _deadline_stages(db, ProjectStage.project_id == project_id)
    return sorted(
        (DueReview(s.id, s.review_deadline.date()) for s in stages if s.review_deadline is not None and s.review_deadline.date() <= as_of),
        key=lambda d: d.due_on,
    )


def _stage_review_pending(db: Session) -> list[ReviewReminder]:
    """Across every project, the stages in review whose deadline is ahead and has not been reminded for its current value."""
    now = datetime.now(UTC)
    stages = _deadline_stages(db, ProjectStage.review_deadline > now)
    projects = {p.id: p for p in db.scalars(select(Project).where(Project.id.in_({s.project_id for s in stages}))).all()} if stages else {}
    reminders: list[ReviewReminder] = []
    for stage in stages:
        project = projects.get(stage.project_id)
        deadline = stage.review_deadline
        if project is None or project.is_archived or deadline is None or stage.review_deadline_reminded_for == deadline.date():
            continue
        reminders.append(ReviewReminder(
            artefact_id=stage.id, project_id=stage.project_id, due_on=deadline.date(), title=f"{project.name}: {stage.name}",
            code="", entity=("project_stage", str(stage.id)), reminded_for=stage.review_deadline_reminded_for, kind="due",
            detail=deadline.isoformat(),
        ))
    return reminders


def _stage_review_mark(db: Session, marks: Sequence[ReminderMark], when: datetime) -> None:
    """Records the reminders sent by stamping the deadline date each was sent for."""
    for stage in db.scalars(select(ProjectStage).where(ProjectStage.id.in_({m.artefact_id for m in marks}))).all():
        stage.review_deadline_reminded_for = next(m.due_on for m in marks if m.artefact_id == stage.id)
    db.flush()


def _stage_review_non_responders(db: Session, reminder: ReviewReminder) -> set[UUID]:
    """The stakeholders of the project who have not responded to the stage's review."""
    if reminder.project_id is None:
        return set()
    stakeholders = get_project_users_by_role(db, reminder.project_id, ProjectRole.STAKEHOLDER)
    responded = set(db.scalars(select(StageReviewResponse.user_id).where(StageReviewResponse.stage_id == reminder.artefact_id)).all())
    return stakeholders - responded


def _stage_review_message(reminder: ReviewReminder, overdue: bool) -> tuple[str, str]:
    """The notification `(title, body)` of the reminder before a stage's review deadline."""
    return (
        f"{reminder.title}: review deadline approaching",
        f"The review deadline is {reminder.detail}. The stage is approved automatically at the deadline unless a "
        "stakeholder rejects it.",
    )


STAGE_REVIEW_ADAPTER = ReviewAdapter(
    schedule="next_review_date", due_reviews=_stage_review_due, pending_reminders=_stage_review_pending,
    mark_reminded=_stage_review_mark, notification_type=NotificationType.STAGE_REVIEW_DEADLINE.value,
    message=_stage_review_message, also_notify=_stage_review_non_responders,
)
"""How the review engine reads a stage's review deadline (registered in `services.reviews.CORE_REVIEW_ADAPTERS` as
`stage_review`)."""

STAGE_REVIEW_TYPE = "stage_review"
