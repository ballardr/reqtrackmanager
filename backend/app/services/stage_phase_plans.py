"""
Module: services.stage_phase_plans

The schedule of a stage's phases, and the reminders about it.

Responsibilities:
- Read and write a phase's expected completion range (`StagePhasePlan`), for a stage or one component's track
  (`services.component_stages`); record actual start and completion when a stage or track moves
  (`record_move`, from `stage_workflows.apply_phase_move`) and notify recipients when a scheduled phase completes.
- `scheduled_phases`: the plan rows that apply now, shared by the overview figures and the review engine's adapter
  (`STAGE_PHASE_REVIEW_ADAPTER`: "upcoming" before the expected start, "overdue" after the expected end); resolve the lead
  time (own, nearest ancestor's, default).

Design decisions:
- `expected_from`/`expected_to` are calendar dates in the planner's day; `started_at`/`completed_at` are UTC instants.
  The sweep has no caller day, so "upcoming" compares against the latest day anywhere (UTC+14) and "overdue" needs the
  date to have passed everywhere (UTC-12) (**Decided by: Agent**).
- Each date is reminded once (marker columns hold the date notified); moving a date re-arms it.
- Recipients are the owner (a user, or every member of a group), then the review policy's default owner, then the project
  managers (**Decided by: User**; the default owner, **Decided by: Agent**); the actor of a move is not told. The review
  policy's lead overrides the project's phase lead time. A phase completes when its stage or track leaves it forward or enters a closed phase;
  moving back reopens it. Only phases with dates send completion reminders (**Decided by: Agent**).
- Component plans are inert, but kept, while component phases are off. Plan rows do not inherit; only the lead time does.

Dependencies: `stage_workflows`, `component_stages`, `principals`, `notifications`, `rbac`, `modules.seams` (the adapter).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Final, Literal

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.enums import StagePhaseKind
from app.models.notification import NotificationType
from app.models.project import Project, ProjectComponent, ProjectStage
from app.models.stage_workflow import ComponentStageState, StagePhasePlan, StageWorkflowPhase
from app.models.user import User
from app.modules.seams import DueReview, ReminderMark, ReviewAdapter, ReviewReminder
from app.schemas.principal import PrincipalRef
from app.services import component_stages
from app.services.audit import log_event
from app.services.notifications import notify
from app.services.principals import principal_recipients, principal_ref
from app.services.project_hierarchy import get_project_chain_ids
from app.services.rbac import get_effective_project_managers
from app.services.stage_workflows import WorkflowConflict, phase_index, phases_by_workflow

#: Days before a phase's expected start that the "upcoming" reminder is sent, when no setting applies.
DEFAULT_LEAD_DAYS: Final = 7
#: Largest lead time a project can set.
MAX_LEAD_DAYS: Final = 365
#: The latest and earliest UTC offsets in use, in hours (see the module docstring).
_LATEST_OFFSET_HOURS: Final = 14
_EARLIEST_OFFSET_HOURS: Final = 12


def resolve_lead_days(db: Session, project: Project) -> tuple[int, bool]:
    """The reminder lead time that applies to `project` and whether it is inherited (or the default).

    Returns:
        `(days, inherited)`: the project's own setting if set, else the nearest ancestor's, else `DEFAULT_LEAD_DAYS`.
    """
    for index, project_id in enumerate(get_project_chain_ids(db, project.id)):
        days = db.scalar(select(Project.phase_reminder_lead_days).where(Project.id == project_id))
        if days is not None:
            return days, index > 0
    return DEFAULT_LEAD_DAYS, True


def set_lead_days(db: Session, project: Project, days: int | None, actor_id: uuid.UUID) -> None:
    """Sets the project's own lead time (None follows the nearest ancestor); audited, not committed.

    Raises:
        ValueError: `days` is outside 0 to `MAX_LEAD_DAYS`.
    """
    if days is not None and not 0 <= days <= MAX_LEAD_DAYS:
        raise ValueError(f"The lead time must be between 0 and {MAX_LEAD_DAYS} days.")
    project.phase_reminder_lead_days = days
    log_event(
        db, entity_type="project", entity_id=project.id, action="phase_reminder_lead_days_changed", actor_id=actor_id,
        project_id=project.id, detail={"days": days},
    )


def project_plans(db: Session, project: Project) -> list[StagePhasePlan]:
    """Every plan row of the project, in one query."""
    return list(db.scalars(select(StagePhasePlan).where(StagePhasePlan.project_id == project.id)).all())


def _find(db: Session, stage_id: uuid.UUID, component_id: uuid.UUID | None, phase_id: uuid.UUID) -> StagePhasePlan | None:
    where = StagePhasePlan.component_id.is_(None) if component_id is None else StagePhasePlan.component_id == component_id
    return db.scalar(select(StagePhasePlan).where(StagePhasePlan.stage_id == stage_id, StagePhasePlan.phase_id == phase_id, where))


def _ensure(db: Session, project_id: uuid.UUID, stage_id: uuid.UUID, component_id: uuid.UUID | None, phase_id: uuid.UUID) -> StagePhasePlan:
    row = _find(db, stage_id, component_id, phase_id)
    if row is None:
        row = StagePhasePlan(project_id=project_id, stage_id=stage_id, component_id=component_id, phase_id=phase_id)
        db.add(row)
        db.flush()
    return row


def set_plan(
    db: Session, project: Project, stage: ProjectStage, phase: StageWorkflowPhase, actor: User, *,
    component: ProjectComponent | None, expected_from: date | None, expected_to: date | None,
) -> StagePhasePlan | None:
    """Sets (or with both dates empty, clears) a phase's expected range (flushed, not committed; audited).

    A cleared range keeps the row while it holds actual dates, so the history is never lost.

    Returns:
        The plan row, or None when nothing remains to store.

    Raises:
        ValueError: `expected_from` is after `expected_to`, or `phase` is not in the workflow that governs the holder.
        WorkflowConflict: A component is given but component phases are off, or the component's track is not applicable.
    """
    if expected_from is not None and expected_to is not None and expected_from > expected_to:
        raise ValueError("The expected start must not be after the expected end.")
    component_id: uuid.UUID | None = None
    workflow_id = stage.workflow_id
    if component is not None:
        if not component_stages.phases_enabled(db, project):
            raise WorkflowConflict("Component phases are off for this project.")
        state = component_stages.get_state(db, component.id, stage.id)
        if state is not None and state.not_applicable:
            raise WorkflowConflict("This stage is not applicable to the component, so its phases cannot be scheduled.")
        workflow_id = state.workflow_id if state is not None else stage.workflow_id
        component_id = component.id
    if phase.workflow_id != workflow_id:
        raise ValueError("The phase is not part of the workflow that applies here.")

    row = _find(db, stage.id, component_id, phase.id)
    if row is None and expected_from is None and expected_to is None:
        return None
    if row is None:
        row = _ensure(db, project.id, stage.id, component_id, phase.id)
    row.expected_from = expected_from
    row.expected_to = expected_to
    detail: dict[str, str | None] = {
        "phase": phase.name, "expected_from": expected_from.isoformat() if expected_from else None,
        "expected_to": expected_to.isoformat() if expected_to else None, "stage_id": str(stage.id),
    }
    if component_id is not None:
        detail["component_id"] = str(component_id)
    log_event(db, entity_type="stage_phase_plan", entity_id=row.id, action="scheduled", actor_id=actor.id, project_id=project.id, detail=detail)
    if expected_from is None and expected_to is None and row.started_at is None and row.completed_at is None:
        db.delete(row)
        db.flush()
        return None
    db.flush()
    return row


def recipients(
    db: Session, project: Project, stage: ProjectStage, state: ComponentStageState | None, *, exclude: set[uuid.UUID] | None = None,
) -> set[uuid.UUID]:
    """The users to tell about a phase: the owner (every member of a group), else the project managers.

    A component's track owner is used when set, else the stage's owner, else the project managers (so a group
    with no one left to notify also falls through to the managers).
    """
    owners = []
    if state is not None:
        owners.append(principal_ref(state.owner_type, state.owner_id))
    found = principal_recipients(db, owners, exclude=exclude or ())
    if not found:
        found = principal_recipients(db, [principal_ref(stage.owner_type, stage.owner_id)], exclude=exclude or ())
    if not found:
        found = get_effective_project_managers(db, project.id) - (exclude or set())
    return found


def _range_text(row: StagePhasePlan) -> str:
    start = row.expected_from.isoformat() if row.expected_from else "not set"
    end = row.expected_to.isoformat() if row.expected_to else "not set"
    return f"Expected {start} to {end}."


def _subject(project: Project, stage: ProjectStage, component_name: str | None, phase_name: str) -> str:
    where = f"{stage.name} / {component_name}" if component_name else stage.name
    return f"{project.name}: {where}, phase {phase_name!r}"


def _send(
    db: Session, user_ids: set[uuid.UUID], kind: NotificationType, project: Project, stage: ProjectStage, title: str, body: str,
    actor_id: uuid.UUID | None = None,
) -> None:
    for user_id in user_ids:
        user = db.get(User, user_id)
        if user is not None:
            notify(
                db, user, notification_type=kind, title=title, body=body, project_id=project.id,
                entity_type="project_stage", entity_id=str(stage.id), actor_id=actor_id,
            )


def record_move(
    db: Session, project: Project, stage: ProjectStage, holder: ProjectStage | ComponentStageState, old_phase_id: uuid.UUID,
    new_phase: StageWorkflowPhase, actor: User, *, component_id: uuid.UUID | None = None,
) -> None:
    """Records the actual dates of a move between phases and tells the recipients a scheduled phase completed.

    Entering a phase stamps its start (once) and reopens it; leaving a phase forward, or entering a closed one,
    completes the phase left, and entering a closed phase completes it too. Flushed, not committed.

    Args:
        holder: The stage or component state that moved.
        old_phase_id: The phase it was in before the move.
        new_phase: The phase it is in now.
        component_id: Set when `holder` is a component's state.
    """
    now = datetime.now(UTC)
    phases = phase_index(db, {old_phase_id, new_phase.id})
    old = phases.get(old_phase_id)
    if old is None:
        return
    forward = new_phase.sort_order > old.sort_order or new_phase.kind == StagePhaseKind.CLOSED
    entered = _ensure(db, project.id, stage.id, component_id, new_phase.id)
    entered.started_at = entered.started_at or now
    entered.completed_at = now if new_phase.kind == StagePhaseKind.CLOSED else None
    left = _find(db, stage.id, component_id, old.id)
    if forward:
        left = left or _ensure(db, project.id, stage.id, component_id, old.id)
        left.completed_at = now
    elif left is not None and old.kind == StagePhaseKind.CLOSED:
        left.completed_at = None
    db.flush()
    if not forward or left is None or (left.expected_from is None and left.expected_to is None):
        return

    state = holder if isinstance(holder, ComponentStageState) else None
    component = db.get(ProjectComponent, component_id) if component_id is not None else None
    title = f"{_subject(project, stage, component.name if component else None, old.name)} completed"
    body = f"{_range_text(left)} Completed {now.date().isoformat()} (UTC); now in {new_phase.name!r}."
    _send(db, recipients(db, project, stage, state, exclude={actor.id}), NotificationType.STAGE_PHASE_COMPLETED, project, stage, title, body)


@dataclass(frozen=True)
class ScheduledPhase:
    """One scheduled phase row with what decides whether it still matters.

    Attributes:
        plan: The plan row.
        project: Its project.
        stage: Its stage.
        state: The component's track state, `None` for a stage's own phase or a component with no stored track.
        component: The component of a track's phase, `None` for a stage's own phase.
        phase: The scheduled phase.
        current: The phase the stage or track is in now.
    """

    plan: StagePhasePlan
    project: Project
    stage: ProjectStage
    state: ComponentStageState | None
    component: ProjectComponent | None
    phase: StageWorkflowPhase
    current: StageWorkflowPhase

    @property
    def is_current(self) -> bool:
        """Whether the scheduled phase is the one the stage or track is in."""
        return self.phase.id == self.current.id

    @property
    def ahead(self) -> bool:
        """Whether the scheduled phase comes after the current one."""
        return not self.is_current and self.phase.sort_order > self.current.sort_order


def scheduled_phases(db: Session, plans: Sequence[StagePhasePlan], *, skip_archived: bool) -> list[ScheduledPhase]:
    """The plan rows that apply now, each with its stage, track and current phase, read in a fixed number of queries.

    A component's plan is left out while component phases are off, for a track that is not applicable and for a phase of
    another workflow than the one the track follows (rows are kept, so switching back restores them).

    Args:
        db: Active session (read only).
        plans: Plan rows of any projects.
        skip_archived: Leave out the rows of archived projects.

    Returns:
        The applicable rows in the order of `plans`.
    """
    if not plans:
        return []
    stages = {s.id: s for s in db.scalars(select(ProjectStage).where(ProjectStage.id.in_({p.stage_id for p in plans}))).all()}
    projects = {p.id: p for p in db.scalars(select(Project).where(Project.id.in_({p.project_id for p in plans}))).all()}
    states = {
        (s.component_id, s.stage_id): s
        for s in db.scalars(select(ComponentStageState).where(ComponentStageState.stage_id.in_(stages.keys()))).all()
    }
    components = {
        c.id: c for c in db.scalars(select(ProjectComponent).where(ProjectComponent.id.in_({p.component_id for p in plans if p.component_id}))).all()
    }
    starts = {
        workflow_id: phases[0].id
        for workflow_id, phases in phases_by_workflow(db, list({s.workflow_id for s in stages.values()})).items() if phases
    }
    phases = phase_index(
        db,
        {p.phase_id for p in plans} | {s.phase_id for s in stages.values()} | {s.phase_id for s in states.values()} | set(starts.values()),
    )
    enabled: dict[uuid.UUID, bool] = {}
    found: list[ScheduledPhase] = []
    for plan in plans:
        stage, project, phase = stages.get(plan.stage_id), projects.get(plan.project_id), phases.get(plan.phase_id)
        if stage is None or project is None or phase is None or (skip_archived and project.is_archived):
            continue
        state = None
        if plan.component_id is not None:
            if project.id not in enabled:
                enabled[project.id] = component_stages.phases_enabled(db, project)
            state = states.get((plan.component_id, stage.id))
            if not enabled[project.id] or (state is not None and state.not_applicable):
                continue
        if phase.workflow_id != (state.workflow_id if state is not None else stage.workflow_id):
            continue
        current_id: uuid.UUID | None
        if state is not None:
            current_id = state.phase_id
        elif plan.component_id is not None:
            current_id = starts.get(stage.workflow_id)
        else:
            current_id = stage.phase_id
        current = phases.get(current_id) if current_id is not None else None
        if current is None:
            continue
        component = components.get(plan.component_id) if plan.component_id is not None else None
        found.append(ScheduledPhase(plan, project, stage, state, component, phase, current))
    return found


def phase_attention_counts(db: Session, project: Project, today: date) -> tuple[int, int]:
    """How many scheduled phases of `project` are overdue and how many start soon, for the overview figures.

    Overdue: a phase that is the stage's (or an applicable component track's) current one, not closed, whose expected end
    is before `today`. Upcoming: a phase ahead of the current one whose expected start is from `today` to the project's
    lead time ahead. The same reading as the daily reminders, evaluated for the viewer's own day; a component's plan counts
    only while component phases are on, for a track that applies and for a phase of the workflow the track follows.

    Args:
        db: The session (read only).
        project: The project.
        today: The viewer's calendar day (`client_date.effective_today()`).

    Returns:
        `(overdue, upcoming)`.
    """
    plans = [p for p in project_plans(db, project) if p.completed_at is None and (p.expected_from or p.expected_to)]
    if not plans:
        return 0, 0
    lead_end = today + timedelta(days=resolve_lead_days(db, project)[0])
    overdue = upcoming = 0
    for item in scheduled_phases(db, plans, skip_archived=False):
        plan = item.plan
        if item.is_current:
            if item.current.kind != StagePhaseKind.CLOSED and plan.expected_to is not None and plan.expected_to < today:
                overdue += 1
        elif item.ahead and plan.expected_from is not None and today <= plan.expected_from <= lead_end:
            upcoming += 1
    return overdue, upcoming


# --- the review engine's adapter for phase schedules --------------------------------------------------


def _reminder_owner(db: Session, item: ScheduledPhase) -> PrincipalRef | None:
    """Who is told of a phase: the track's owner when it names anyone to tell, else the stage's owner."""
    if item.state is not None:
        track_owner = principal_ref(item.state.owner_type, item.state.owner_id)
        if track_owner is not None and principal_recipients(db, [track_owner]):
            return track_owner
    return principal_ref(item.stage.owner_type, item.stage.owner_id)


def _phase_due_reviews(db: Session, project_id: uuid.UUID, as_of: date) -> list[DueReview]:
    """The project's current phases whose expected end is before `as_of` (overdue), oldest first."""
    project = db.get(Project, project_id)
    if project is None:
        return []
    plans = [p for p in project_plans(db, project) if p.completed_at is None and p.expected_to is not None and p.expected_to < as_of]
    due = [
        DueReview(item.plan.id, item.plan.expected_to, _reminder_owner(db, item))
        for item in scheduled_phases(db, plans, skip_archived=False)
        if item.is_current and item.current.kind != StagePhaseKind.CLOSED and item.plan.expected_to is not None
    ]
    return sorted(due, key=lambda d: d.due_on)


def _phase_reminder(
    item: ScheduledPhase, owner: PrincipalRef | None, due_on: date, kind: Literal["due", "overdue"],
) -> ReviewReminder:
    """The engine reminder for one date of a scheduled phase."""
    plan = item.plan
    return ReviewReminder(
        artefact_id=plan.id, project_id=plan.project_id, due_on=due_on, owner=owner,
        title=_subject(item.project, item.stage, item.component.name if item.component else None, item.phase.name), code="",
        entity=("project_stage", str(item.stage.id)), reminded_for=plan.upcoming_notified_for,
        overdue_reminded_for=plan.overdue_notified_for, kind=kind, detail=_range_text(plan),
    )


def _phase_pending_reminders(db: Session) -> list[ReviewReminder]:
    """Across every project, the phase dates whose reminder has not been sent for their current value.

    A phase ahead of the current one yields an "upcoming" reminder against its expected start; the current phase, while not
    closed, yields an "overdue" one against its expected end. The engine decides whether the day has come.
    """
    rows = list(db.scalars(
        select(StagePhasePlan).where(
            StagePhasePlan.completed_at.is_(None),
            or_(
                StagePhasePlan.expected_from.is_not(None) & (StagePhasePlan.upcoming_notified_for.is_distinct_from(StagePhasePlan.expected_from)),
                StagePhasePlan.expected_to.is_not(None) & (StagePhasePlan.overdue_notified_for.is_distinct_from(StagePhasePlan.expected_to)),
            ),
        )
    ).all())
    reminders: list[ReviewReminder] = []
    for item in scheduled_phases(db, rows, skip_archived=True):
        plan = item.plan
        owner = _reminder_owner(db, item)
        if item.ahead and plan.expected_from is not None and plan.upcoming_notified_for != plan.expected_from:
            reminders.append(_phase_reminder(item, owner, plan.expected_from, "due"))
        if (
            item.is_current and item.current.kind != StagePhaseKind.CLOSED and plan.expected_to is not None
            and plan.overdue_notified_for != plan.expected_to
        ):
            reminders.append(_phase_reminder(item, owner, plan.expected_to, "overdue"))
    return reminders


def _phase_mark_reminded(db: Session, marks: Sequence[ReminderMark], when: datetime) -> None:
    """Records the phase reminders the engine sent by stamping the date each was sent for."""
    rows = {r.id: r for r in db.scalars(select(StagePhasePlan).where(StagePhasePlan.id.in_({m.artefact_id for m in marks}))).all()}
    for mark in marks:
        row = rows.get(mark.artefact_id)
        if row is None:
            continue
        if mark.overdue:
            row.overdue_notified_for = mark.due_on
        else:
            row.upcoming_notified_for = mark.due_on
    db.flush()


def _phase_message(reminder: ReviewReminder, overdue: bool) -> tuple[str, str]:
    """The notification `(title, body)` of an upcoming or overdue phase."""
    if overdue:
        return f"{reminder.title} is overdue (expected end {reminder.due_on.isoformat()})", reminder.detail
    return f"{reminder.title} is due to start on {reminder.due_on.isoformat()}", reminder.detail


def _phase_reminder_day(now: datetime, kind: Literal["due", "overdue"]) -> date:
    """The day a phase reminder is judged against: the latest day anywhere for "upcoming", the earliest for "overdue"."""
    if kind == "due":
        return (now + timedelta(hours=_LATEST_OFFSET_HOURS)).date()
    return (now - timedelta(hours=_EARLIEST_OFFSET_HOURS)).date()


def _phase_project_lead(db: Session, project_id: uuid.UUID) -> int | None:
    """The project's phase lead time (own, nearest ancestor's, default), or `None` when the project is gone."""
    project = db.get(Project, project_id)
    return None if project is None else resolve_lead_days(db, project)[0]


PHASE_SCHEDULE_TYPE: Final = "stage_phase"

STAGE_PHASE_REVIEW_ADAPTER = ReviewAdapter(
    schedule="next_review_date", due_reviews=_phase_due_reviews, pending_reminders=_phase_pending_reminders,
    mark_reminded=_phase_mark_reminded, notification_type=NotificationType.STAGE_PHASE_UPCOMING.value,
    overdue_notification_type=NotificationType.STAGE_PHASE_OVERDUE.value, message=_phase_message,
    project_lead_days=_phase_project_lead, reminder_day=_phase_reminder_day,
)
"""How the review engine reads the phase schedules of stages and component tracks (registered in
`services.reviews.CORE_REVIEW_ADAPTERS` as `stage_phase`)."""
