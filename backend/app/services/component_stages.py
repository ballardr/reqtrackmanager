"""
Module: services.component_stages

Component phases: with the project switch on, each component follows a workflow for each project stage.

Responsibilities:
- Resolve the project's `component_phases_mode` (own setting, else the nearest ancestor's, else off).
- Read every component's track (workflow, phase, owner, "not applicable") for a project's stages in a few
  queries; a component with no row follows the stage's workflow at its starting phase.
- Change a track (workflow, owner, not applicable) and move it between phases through the same
  `stage_workflows.apply_phase_move` a stage uses, so a locked phase baselines and approves only that
  component's requirements for the stage.
- Say which components a project stage's own lock leaves to their tracks (`tracked_component_ids`).

Design decisions:
- Off means inert: nothing is read, shown or applied, and the project stage is the only phase (rows are kept,
  so switching back on restores them). A project with the switch unset behaves exactly as before.
- A component's lock approves that component's requirements that target that stage (Decided by: User), and the
  project stage's own lock then skips components that have an applicable track for it (Decided by: User).
- The track's owner (a user or a group) may move it, including into and out of a locked phase, as well as a
  project manager (Decided by: User; recorded in the SOC 2 review, because a nominee can then approve).
- Progression between stages is advisory (Decided by: User): a component can start the next stage at any time;
  `previous_closed` only tells the screen whether the earlier stage has reached a closed phase.
- A track may change workflow, or become not applicable, only while it is in an open phase with no baseline of
  its own, the rule a stage follows, so an edit cannot unlock approved requirements.
- Nested projects: a state, not a definition table, so there is no fallback; only the switch inherits.

Dependencies: `services.stage_workflows` (phases, moves), `services.principals` (owner), `services.rbac`.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final, Literal

from sqlalchemy import and_, false, or_, select, true, tuple_
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.models.enums import ProjectRole, StagePhaseKind
from app.models.project import Project, ProjectComponent, ProjectStage
from app.models.requirement import Baseline, Requirement, RequirementVersion
from app.models.stage_workflow import ComponentStageState, StageWorkflowPhase
from app.models.user import User
from app.schemas.principal import PrincipalRef
from app.services.audit import log_event
from app.services.principals import is_principal_member, principal_columns, principal_ref, validate_principal
from app.services.project_hierarchy import get_project_chain_ids
from app.services.stage_workflows import (
    WorkflowConflict,
    apply_phase_move,
    effective_workflows,
    phase_index,
    start_phase,
)

MODE_ON: Final = "on"
MODE_OFF: Final = "off"
Mode = Literal["on", "off"]


class _Unset:
    """Marks a field a request did not send, so `None` can mean "clear it"."""


UNSET = _Unset()


@dataclass
class Track:
    """One component's standing in one stage.

    Attributes:
        state: The stored row, or None when the component still follows the stage's defaults.
        workflow_id / phase_id: What applies (the row's, else the stage's workflow at its starting phase).
        previous_closed: Whether the previous stage (by order) has reached a closed phase for this component
            (its own track's phase, else the stage's); advisory only.
    """

    component_id: uuid.UUID
    stage_id: uuid.UUID
    workflow_id: uuid.UUID
    phase_id: uuid.UUID
    not_applicable: bool
    state: ComponentStageState | None
    previous_closed: bool


def resolve_mode(db: Session, project: Project) -> tuple[Mode, bool]:
    """The component-phases mode that applies to `project` and whether it is inherited.

    Returns:
        `(mode, inherited)`: the project's own setting if set, else the nearest ancestor's, else `"off"`.
    """
    for index, project_id in enumerate(get_project_chain_ids(db, project.id)):
        mode = db.scalar(select(Project.component_phases_mode).where(Project.id == project_id))
        if mode == MODE_ON:
            return MODE_ON, index > 0
        if mode == MODE_OFF:
            return MODE_OFF, index > 0
    return MODE_OFF, True


def phases_enabled(db: Session, project: Project) -> bool:
    """True when component phases are on for the project."""
    return resolve_mode(db, project)[0] == MODE_ON


def set_mode(db: Session, project: Project, mode: str | None, actor_id: uuid.UUID) -> None:
    """Sets the project's own switch (`on`, `off`, or None to follow the nearest ancestor); audited, not committed.

    Raises:
        ValueError: `mode` is not `on`, `off` or None.
    """
    if mode not in (MODE_ON, MODE_OFF, None):
        raise ValueError("The mode must be 'on', 'off' or empty (inherit).")
    project.component_phases_mode = mode
    log_event(
        db, entity_type="project", entity_id=project.id, action="component_phases_mode_changed", actor_id=actor_id,
        project_id=project.id, detail={"mode": mode},
    )


def tracked_component_ids(db: Session, project: Project, stage: ProjectStage) -> set[uuid.UUID]:
    """Components whose own track governs `stage`: the switch is on and the component has an applicable row.

    A project stage's own lock and completion leave these components' requirements to their tracks.
    """
    if not phases_enabled(db, project):
        return set()
    return set(
        db.scalars(
            select(ComponentStageState.component_id).where(
                ComponentStageState.stage_id == stage.id, ComponentStageState.not_applicable.is_(False)
            )
        ).all()
    )


@dataclass(frozen=True)
class PhaseRef:
    """The phase that governs a requirement: its name and kind."""

    name: str
    kind: StagePhaseKind


def requirement_phase_lookup(db: Session, project: Project) -> Callable[[uuid.UUID, uuid.UUID], PhaseRef | None]:
    """A function giving the phase that governs a requirement of `project`, read once however many requirements are asked.

    A requirement is governed by its component's own track for its target stage when component phases are on and the
    component has an applicable track there, else by the stage's own phase; a component marked not applicable to the stage
    has no governing phase (`None`). The same rule the approval and lock use (`tracked_component_ids`), so the list
    never shows a phase that is not the one in force.

    Args:
        db: The session (read only).
        project: The project whose requirements are listed.

    Returns:
        `lookup(component_id, target_stage_id)`.
    """
    stages = {s.id: s for s in db.scalars(select(ProjectStage).where(ProjectStage.project_id == project.id)).all()}
    states: dict[tuple[uuid.UUID, uuid.UUID], ComponentStageState] = {}
    if phases_enabled(db, project):
        for st in db.scalars(select(ComponentStageState).where(ComponentStageState.project_id == project.id)).all():
            states[(st.component_id, st.stage_id)] = st
    phases = phase_index(db, {s.phase_id for s in stages.values()} | {st.phase_id for st in states.values()})

    def lookup(component_id: uuid.UUID, stage_id: uuid.UUID) -> PhaseRef | None:
        stage = stages.get(stage_id)
        if stage is None:
            return None
        state = states.get((component_id, stage_id))
        if state is not None and state.not_applicable:
            return None
        phase = phases.get(state.phase_id if state is not None else stage.phase_id)
        return PhaseRef(phase.name, phase.kind) if phase is not None else None

    return lookup


def requirement_phase_clause(db: Session, project: Project, name: str) -> ColumnElement[bool]:
    """A condition on `Requirement` and its current `RequirementVersion` that keeps the requirements whose governing phase
    (see `requirement_phase_lookup`) is called `name` (compared without case).

    Built from the project's stages and tracks read once, so the filter is a plain SQL condition and paging stays in the database.
    """
    needle = name.strip().lower()
    stages = list(db.scalars(select(ProjectStage).where(ProjectStage.project_id == project.id)).all())
    states = (
        list(db.scalars(select(ComponentStageState).where(ComponentStageState.project_id == project.id)).all())
        if phases_enabled(db, project) else []
    )
    phases = phase_index(db, {s.phase_id for s in stages} | {st.phase_id for st in states})

    def named(phase_id: uuid.UUID) -> bool:
        phase = phases.get(phase_id)
        return phase is not None and phase.name.lower() == needle

    pair = tuple_(Requirement.component_id, RequirementVersion.target_stage_id)
    stage_ids = [s.id for s in stages if named(s.phase_id)]
    all_pairs = [(st.component_id, st.stage_id) for st in states]
    track_pairs = [(st.component_id, st.stage_id) for st in states if not st.not_applicable and named(st.phase_id)]
    by_stage = (
        and_(RequirementVersion.target_stage_id.in_(stage_ids), pair.not_in(all_pairs) if all_pairs else true()) if stage_ids else false()
    )
    return or_(by_stage, pair.in_(track_pairs) if track_pairs else false())


def project_tracks(db: Session, project: Project) -> list[Track]:
    """Every component's track for every stage of the project, read in a fixed number of queries.

    Returns an empty list when the switch is off. Ordered by component then stage order.
    """
    if not phases_enabled(db, project):
        return []
    components = list(db.scalars(
        select(ProjectComponent).where(ProjectComponent.project_id == project.id)
        .order_by(ProjectComponent.sort_order, ProjectComponent.name)
    ).all())
    stages = list(db.scalars(
        select(ProjectStage).where(ProjectStage.project_id == project.id).order_by(ProjectStage.sort_order)
    ).all())
    rows = {
        (r.component_id, r.stage_id): r
        for r in db.scalars(select(ComponentStageState).where(ComponentStageState.project_id == project.id)).all()
    }
    starts = {s.id: start_phase(db, s.workflow_id).id for s in stages}
    phases = phase_index(db, set(starts.values()) | {s.phase_id for s in stages} | {r.phase_id for r in rows.values()})
    tracks: list[Track] = []
    for component in components:
        previous_phase: uuid.UUID | None = None
        for stage in stages:
            row = rows.get((component.id, stage.id))
            if row is not None:
                workflow_id, phase_id, na = row.workflow_id, row.phase_id, row.not_applicable
            else:
                workflow_id, phase_id, na = stage.workflow_id, starts[stage.id], False
            earlier = phases.get(previous_phase) if previous_phase is not None else None
            previous_closed = earlier is not None and earlier.kind == StagePhaseKind.CLOSED
            tracks.append(Track(component.id, stage.id, workflow_id, phase_id, na, row, previous_closed))
            previous_phase = phase_id
    return tracks


def get_state(db: Session, component_id: uuid.UUID, stage_id: uuid.UUID) -> ComponentStageState | None:
    """The stored row for a component and stage, or None."""
    return db.scalar(
        select(ComponentStageState).where(ComponentStageState.component_id == component_id, ComponentStageState.stage_id == stage_id)
    )


def ensure_state(db: Session, project: Project, component: ProjectComponent, stage: ProjectStage) -> ComponentStageState:
    """The component's row for the stage, created at the stage's workflow and starting phase when absent (flushed)."""
    state = get_state(db, component.id, stage.id)
    if state is None:
        state = ComponentStageState(
            project_id=project.id, component_id=component.id, stage_id=stage.id, workflow_id=stage.workflow_id,
            phase_id=start_phase(db, stage.workflow_id).id,
        )
        db.add(state)
        db.flush()
    return state


def _has_own_baseline(db: Session, state: ComponentStageState) -> bool:
    return db.scalar(
        select(Baseline.id).where(Baseline.stage_id == state.stage_id, Baseline.component_id == state.component_id).limit(1)
    ) is not None


def _kind(db: Session, phase_id: uuid.UUID) -> StagePhaseKind:
    kind = db.scalar(select(StageWorkflowPhase.kind).where(StageWorkflowPhase.id == phase_id))
    if kind is None:
        raise ValueError("The track's phase no longer exists.")
    return kind


def update_track(
    db: Session, project: Project, component: ProjectComponent, stage: ProjectStage, actor: User, *,
    workflow_id: uuid.UUID | None | _Unset = UNSET, not_applicable: bool | _Unset = UNSET,
    owner: PrincipalRef | None | _Unset = UNSET,
) -> ComponentStageState:
    """Changes a track's workflow, owner or "not applicable" flag (flushed, not committed; audited).

    A change of workflow starts the track at the new workflow's first phase. `workflow_id=None` returns to the
    stage's workflow.

    Raises:
        WorkflowConflict: Component phases are off, or a workflow or applicability change is made while the track
            is outside an open phase or already has a baseline of its own.
        ValueError: The workflow is not available to the project, or the owner is not valid for this project.
        HTTPException: 400 from `validate_principal` for an owner who cannot be named.
    """
    if not phases_enabled(db, project):
        raise WorkflowConflict("Component phases are off for this project.")
    state = ensure_state(db, project, component, stage)
    detail: dict[str, str | bool | None] = {"component_id": str(component.id), "stage_id": str(stage.id)}

    changes_structure = (
        (not isinstance(workflow_id, _Unset) and (workflow_id or stage.workflow_id) != state.workflow_id)
        or (not isinstance(not_applicable, _Unset) and not_applicable != state.not_applicable)
    )
    if changes_structure and (_kind(db, state.phase_id) != StagePhaseKind.OPEN or _has_own_baseline(db, state)):
        raise WorkflowConflict(
            "A track can change workflow or applicability only while it is in an open phase and has no baseline."
        )
    if not isinstance(workflow_id, _Unset):
        chosen = workflow_id or stage.workflow_id
        if chosen != state.workflow_id:
            if chosen not in {w.id for w in effective_workflows(db, project)}:
                raise ValueError("workflow_id must be a workflow available to this project.")
            state.workflow_id = chosen
            state.phase_id = start_phase(db, chosen).id
            detail["workflow_id"] = str(chosen)
    if not isinstance(not_applicable, _Unset) and not_applicable != state.not_applicable:
        state.not_applicable = not_applicable
        detail["not_applicable"] = not_applicable
    if not isinstance(owner, _Unset):
        validate_principal(db, owner, organization_id=project.organization_id, project_id=project.id, field="owner")
        for key, value in principal_columns("owner", owner).items():
            setattr(state, key, value)
        detail["owner_type"] = owner.type.value if owner else None
        detail["owner_id"] = str(owner.id) if owner else None
    log_event(db, entity_type="component_stage_state", entity_id=state.id, action="updated", actor_id=actor.id,
              project_id=project.id, detail=detail)
    db.flush()
    return state


def owner_of(state: ComponentStageState | None) -> PrincipalRef | None:
    """The track's owner as a principal reference, or None."""
    return principal_ref(state.owner_type, state.owner_id) if state is not None else None


def may_move_locked(db: Session, state: ComponentStageState | None, user_id: uuid.UUID, roles: set[ProjectRole] | frozenset[ProjectRole]) -> bool:
    """True when the user may move the track into or out of a locked phase: a project manager, or a member of
    the track's owner (a user, or a group by effective membership)."""
    if ProjectRole.PROJECT_MANAGER in roles:
        return True
    return is_principal_member(db, owner_of(state), user_id)


def move_track(
    db: Session, project: Project, component: ProjectComponent, stage: ProjectStage, phase: StageWorkflowPhase,
    actor: User, *, roles: set[ProjectRole] | frozenset[ProjectRole], cascade_to_requirements: bool = False,
) -> ComponentStageState:
    """Moves a component's track to another phase of its workflow (flushed, not committed).

    The track's row is created first when the component still follows the stage's defaults. Moves are free in
    either direction; the caller has already checked that the actor may move this track at all (a project
    manager or the owner), and this function additionally decides whether the actor may touch a locked phase.

    Raises:
        WorkflowConflict: Component phases are off, the track is not applicable, or it is already in `phase`.
        PermissionError: A locked phase is entered or left by someone who is neither a project manager nor the owner.
        ValueError: `phase` is not in the track's workflow.
    """
    if not phases_enabled(db, project):
        raise WorkflowConflict("Component phases are off for this project.")
    state = ensure_state(db, project, component, stage)
    if state.not_applicable:
        raise WorkflowConflict("This stage is not applicable to the component, so its phase cannot change.")
    apply_phase_move(
        db, project, stage, state, phase, actor, can_lock=may_move_locked(db, state, actor.id, roles),
        cascade_to_requirements=cascade_to_requirements, component_id=component.id,
    )
    return state
