"""
Module: services.stage_phase_plans

The schedule of a stage's phases, and the reminders about it.

Responsibilities:
- Read and write a phase's expected completion range (`StagePhasePlan`), for a project stage's own phase
  or for one component's track within the stage (`services.component_stages`).
- Record the actual start and completion of a phase whenever a stage or a track moves
  (`record_move`, called by `stage_workflows.apply_phase_move`), and tell the recipients when a scheduled
  phase completes.
- The daily sweep (`send_phase_reminders`): an "upcoming" reminder before a phase's expected start and an
  "overdue" reminder when the current phase passes its expected end.
- Resolve the project's reminder lead time (own setting, else the nearest ancestor's, else the default).

Design decisions:
- Time shapes: `expected_from`/`expected_to` are calendar dates in the planner's own day; `started_at` and
  `completed_at` are past instants in UTC. The sweep has no caller, so no local day exists: "upcoming" compares
  against the latest calendar day anywhere (UTC+14) so nobody is reminded late, and "overdue" requires the
  date to have passed everywhere (UTC-12) so nobody is told a deadline was missed while it is still that day
  (Decided by: Agent).
- Each date is reminded once: the marker columns hold the date notified, so moving a date re-arms its reminder
  and a repeated sweep sends nothing.
- Recipients are the owner (a user, or every member of a group), else the project managers (Decided by: User).
  Addressing only, not authorisation. The actor of a move is never told about their own move.
- A phase completes when the stage or track leaves it forward or enters a closed phase; moving back to it
  reopens it. The completion reminder is sent only for a phase that was given dates, so an unscheduled
  stage adds no notifications beyond the stage ones that already exist (Decided by: Agent).
- Component plans are inert while component phases are off (their rows are kept), as the tracks are.
- Nested projects: plan rows are state with no fallback; only the lead time inherits.

Dependencies: `services.stage_workflows`, `services.component_stages`, `services.principals`,
`services.notifications`, `services.rbac`.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Final

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.enums import StagePhaseKind
from app.models.notification import NotificationType
from app.models.project import Project, ProjectComponent, ProjectStage
from app.models.stage_workflow import ComponentStageState, StagePhasePlan, StageWorkflowPhase
from app.models.user import User
from app.services import component_stages
from app.services.audit import log_event
from app.services.notifications import notify
from app.services.principals import principal_recipients, principal_ref
from app.services.project_hierarchy import get_project_chain_ids
from app.services.rbac import get_effective_project_managers
from app.services.stage_workflows import WorkflowConflict, phase_index, start_phase

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


def send_phase_reminders(db: Session, now: datetime | None = None) -> None:
    """Daily sweep: sends the "upcoming" and "overdue" phase reminders, each once per date. Commits once.

    Upcoming: a phase the stage (or track) has not reached yet, ahead of the current phase, whose expected
    start is within the project's lead time of the latest calendar day anywhere. Overdue: the current phase
    whose expected end has passed everywhere. A component's plan is skipped while component phases are off,
    for a track that is not applicable, and for a phase from another workflow than the track follows.

    Args:
        now: The instant to evaluate at (tests); defaults to the current time.
    """
    now = now or datetime.now(UTC)
    latest_today = (now + timedelta(hours=_LATEST_OFFSET_HOURS)).date()
    earliest_today = (now - timedelta(hours=_EARLIEST_OFFSET_HOURS)).date()
    rows = list(db.scalars(
        select(StagePhasePlan).where(
            StagePhasePlan.completed_at.is_(None),
            or_(
                StagePhasePlan.expected_from.is_not(None) & (StagePhasePlan.upcoming_notified_for.is_distinct_from(StagePhasePlan.expected_from)),
                StagePhasePlan.expected_to.is_not(None) & (StagePhasePlan.overdue_notified_for.is_distinct_from(StagePhasePlan.expected_to)),
            ),
        )
    ).all())
    if not rows:
        return
    stages = {s.id: s for s in db.scalars(select(ProjectStage).where(ProjectStage.id.in_({r.stage_id for r in rows}))).all()}
    projects = {p.id: p for p in db.scalars(select(Project).where(Project.id.in_({r.project_id for r in rows}))).all()}
    states = {
        (s.component_id, s.stage_id): s
        for s in db.scalars(select(ComponentStageState).where(ComponentStageState.stage_id.in_(stages.keys()))).all()
    }
    component_ids = {r.component_id for r in rows if r.component_id}
    components = {c.id: c for c in db.scalars(select(ProjectComponent).where(ProjectComponent.id.in_(component_ids))).all()}
    starts: dict[uuid.UUID, uuid.UUID] = {}
    phase_ids = {r.phase_id for r in rows} | {s.phase_id for s in stages.values()} | {s.phase_id for s in states.values()}
    phases = phase_index(db, phase_ids)
    enabled: dict[uuid.UUID, bool] = {}
    lead: dict[uuid.UUID, int] = {}

    for row in rows:
        stage, project, phase = stages.get(row.stage_id), projects.get(row.project_id), phases.get(row.phase_id)
        if stage is None or project is None or phase is None or project.is_archived:
            continue
        state = None
        if row.component_id is not None:
            if project.id not in enabled:
                enabled[project.id] = component_stages.phases_enabled(db, project)
            state = states.get((row.component_id, stage.id))
            if not enabled[project.id] or (state is not None and state.not_applicable):
                continue
        workflow_id = state.workflow_id if state is not None else stage.workflow_id
        if phase.workflow_id != workflow_id:
            continue
        if state is not None:
            current_id = state.phase_id
        elif row.component_id is not None:
            if stage.workflow_id not in starts:
                starts[stage.workflow_id] = start_phase(db, stage.workflow_id).id
            current_id = starts[stage.workflow_id]
        else:
            current_id = stage.phase_id
        current = phases.get(current_id) or phase_index(db, {current_id}).get(current_id)
        if current is None:
            continue
        if project.id not in lead:
            lead[project.id] = resolve_lead_days(db, project)[0]
        component = components.get(row.component_id) if row.component_id else None
        subject = _subject(project, stage, component.name if component else None, phase.name)

        if (
            row.phase_id != current_id and phase.sort_order > current.sort_order and row.expected_from is not None
            and row.upcoming_notified_for != row.expected_from and row.expected_from <= latest_today + timedelta(days=lead[project.id])
        ):
            row.upcoming_notified_for = row.expected_from
            _send(
                db, recipients(db, project, stage, state), NotificationType.STAGE_PHASE_UPCOMING, project, stage,
                f"{subject} is due to start on {row.expected_from.isoformat()}", _range_text(row),
            )
        if (
            row.phase_id == current_id and current.kind != StagePhaseKind.CLOSED and row.expected_to is not None
            and row.overdue_notified_for != row.expected_to and row.expected_to < earliest_today
        ):
            row.overdue_notified_for = row.expected_to
            _send(
                db, recipients(db, project, stage, state), NotificationType.STAGE_PHASE_OVERDUE, project, stage,
                f"{subject} is overdue (expected end {row.expected_to.isoformat()})", _range_text(row),
            )
    db.commit()
