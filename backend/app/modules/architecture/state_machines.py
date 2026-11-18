"""
Module: modules.architecture.state_machines

The rules for state machine diagrams and what they hold: create, edit, move between statuses, archive and delete a
state machine diagram; add, change and delete its states and transitions; save its layout. The modelling checks are in
`state_machine_checks`.

Responsibilities:
- Validate every reference a change stores: the element described (one the viewer may read), a state's parent, a
  transition's two states.
- Advance the diagram's `version` on every change to the diagram or to anything it holds, and write one audit event per
  change holding ids, counts and field names, never names or text.
- Refuse the move to `active` while the checks find an error (`ActivationRefused`); an edit to an active diagram that
  introduces an error is saved and shown, never refused, so a record is never locked out of repair.
- Read lists in bulk (`state_machine_outs`, `state_outs`): one statement per kind of related row however many rows.

Design decisions:
- **One lock for the whole diagram.** A change to a state or a transition quotes the diagram's `version`, and the diagram
  row is locked while it is checked, so two editors cannot both overwrite the drawing.
- **Visibility follows the element.** A state machine diagram is the project's own record, but it describes an element
  that may belong to another owner; every read and write goes through `visibility`, and a diagram whose element the
  person cannot read answers 404, like the element itself.
- **A state follows its diagram.** A state has no status or lock of its own; its code is project-scoped and never
  reused. A state with child states cannot be deleted (move or delete the children first); deleting a state removes its
  transitions (a database cascade) and the links, tags and places that name it.
- **Nesting** is a tree of at most `MAX_STATE_DEPTH` levels whose parents are ordinary states of the same diagram
  (a marker cannot contain anything).

Dependencies: `records` (the shared rule errors, version lock and audit helpers), `visibility`, `service`, core
`services.sequences`, `services.audit`, `services.relationships`.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.user import User
from app.modules.architecture import state_machine_checks as checks
from app.modules.architecture.diagrams import _check_new_element, leaders_of, machine_notes_of, note_out, sync_notes
from app.modules.architecture.enums import AttachPoint, LabelPosition, LeaderKind, LineShape, RecordStatus, StateKind, ValidationSeverity
from app.modules.architecture.models import (
    ArchitectureDiagramNote,
    ArchitectureElement,
    ArchitectureNoteLeader,
    ArchitectureState,
    ArchitectureStateMachineDiagram,
    ArchitectureTransition,
)
from app.modules.architecture.records import RuleError, _check_version, _detail, _forget, _touch
from app.modules.architecture.schemas import (
    NoteIn,
    StateCreate,
    StateMachineDiagramCreate,
    StateMachineDiagramOut,
    StateMachineDiagramUpdate,
    StateMachineLayoutSave,
    StateMachineModel,
    StateOut,
    StateUpdate,
    TransitionIn,
    TransitionOut,
    ValidationIssueOut,
    WaypointIn,
)
from app.modules.architecture.service import (
    STATE_ARTEFACT_TYPE,
    STATE_CODE_PREFIX,
    STATE_MACHINE_ARTEFACT_TYPE,
    STATE_MACHINE_CODE_PREFIX,
)
from app.modules.architecture.transitions import allowed_moves, move_refusal
from app.modules.architecture.visibility import Viewer, visible_element_ids
from app.services.audit import log_event
from app.services.sequences import generate_unique_code

#: The deepest a state tree may be (a top-level state is depth 1).
MAX_STATE_DEPTH = 12

_MARKERS = (StateKind.INITIAL.value, StateKind.FINAL.value, StateKind.CHOICE.value)


class ActivationRefused(RuleError):
    """The move to `active` was refused because the checks found errors.

    Attributes:
        issues: The error issues, which the message lists.
    """

    def __init__(self, issues: Sequence[checks.ValidationIssue]) -> None:
        super().__init__(
            "This state machine diagram cannot be activated until its errors are resolved: "
            + " ".join(f.message for f in issues),
            409,
        )
        self.issues = list(issues)


# --- Lookups ---------------------------------------------------------------


def get_state_machine(
    db: Session, viewer: Viewer, project_id: uuid.UUID, diagram_id: uuid.UUID, *, lock: bool = False,
) -> ArchitectureStateMachineDiagram:
    """The state machine diagram in the project when the viewer may read the element it describes; `lock` takes a row
    lock for a write.

    Raises:
        RuleError: 404 if it does not exist in the project or its element is hidden from the viewer.
    """
    query = select(ArchitectureStateMachineDiagram).where(
        ArchitectureStateMachineDiagram.id == diagram_id, ArchitectureStateMachineDiagram.project_id == project_id,
    )
    diagram = db.scalar(query.with_for_update() if lock else query)
    if diagram is None or diagram.element_id not in visible_element_ids(db, viewer, [diagram.element_id]):
        raise RuleError("State machine diagram not found.", 404)
    return diagram


def list_state_machines(
    db: Session, viewer: Viewer, project_id: uuid.UUID, *, include_archived: bool = False,
) -> list[ArchitectureStateMachineDiagram]:
    """The project's state machine diagrams whose element the viewer may read, ordered by code."""
    query = select(ArchitectureStateMachineDiagram).where(ArchitectureStateMachineDiagram.project_id == project_id)
    if not include_archived:
        query = query.where(ArchitectureStateMachineDiagram.is_archived.is_(False))
    rows = list(db.scalars(query.order_by(ArchitectureStateMachineDiagram.unique_code)))
    readable = visible_element_ids(db, viewer, {r.element_id for r in rows})
    return [r for r in rows if r.element_id in readable]


def get_state(
    db: Session, viewer: Viewer, project_id: uuid.UUID, state_id: uuid.UUID,
) -> tuple[ArchitectureState, ArchitectureStateMachineDiagram]:
    """A state and its diagram, when the viewer may read the diagram's element.

    Raises:
        RuleError: 404 if either is absent from the project or hidden from the viewer.
    """
    state = db.scalar(select(ArchitectureState).where(ArchitectureState.id == state_id, ArchitectureState.project_id == project_id))
    if state is None:
        raise RuleError("State not found.", 404)
    try:
        diagram = get_state_machine(db, viewer, project_id, state.state_machine_diagram_id)
    except RuleError as exc:
        raise RuleError("State not found.", 404) from exc
    return state, diagram


def states_of(db: Session, diagram_id: uuid.UUID) -> list[ArchitectureState]:
    """The diagram's states in code order."""
    return list(db.scalars(
        select(ArchitectureState).where(ArchitectureState.state_machine_diagram_id == diagram_id).order_by(ArchitectureState.unique_code)
    ))


def states_of_many(db: Session, diagram_ids: Iterable[uuid.UUID]) -> list[ArchitectureState]:
    """The states of every named diagram in one statement, in code order (a list reads them this way so its cost does not
    grow with the number of diagrams)."""
    ids = list(diagram_ids)
    if not ids:
        return []
    return list(db.scalars(
        select(ArchitectureState).where(ArchitectureState.state_machine_diagram_id.in_(ids)).order_by(ArchitectureState.unique_code)
    ))


def transitions_of(db: Session, diagram_id: uuid.UUID) -> list[ArchitectureTransition]:
    """The diagram's transitions in order."""
    return list(db.scalars(
        select(ArchitectureTransition).where(ArchitectureTransition.state_machine_diagram_id == diagram_id)
        .order_by(ArchitectureTransition.sort_order, ArchitectureTransition.id)
    ))


def _audit_machine(db: Session, diagram_id: uuid.UUID, action: str, actor: User, project_id: uuid.UUID, **detail: Any) -> None:
    """Writes the audit event for a change to a state machine diagram (or to a transition it holds): ids, counts and
    field names only."""
    log_event(
        db, entity_type=STATE_MACHINE_ARTEFACT_TYPE, entity_id=diagram_id, action=action, actor_id=actor.id,
        project_id=project_id, detail=_detail(detail),
    )


def _audit_state(db: Session, state_id: uuid.UUID, action: str, actor: User, project_id: uuid.UUID, **detail: Any) -> None:
    """Writes the audit event for a change to a state: ids and field names only."""
    log_event(
        db, entity_type=STATE_ARTEFACT_TYPE, entity_id=state_id, action=action, actor_id=actor.id,
        project_id=project_id, detail=_detail(detail),
    )


# --- Diagrams --------------------------------------------------------------


def require_sound(db: Session, diagram: ArchitectureStateMachineDiagram) -> None:
    """Checks that the diagram has no error issue (the gate on the move to `active`).

    Raises:
        ActivationRefused: 409 listing the errors.
    """
    errors = [
        f for f in checks.check(states_of(db, diagram.id), transitions_of(db, diagram.id))
        if f.severity == ValidationSeverity.ERROR
    ]
    if errors:
        raise ActivationRefused(errors)


def create_state_machine(
    db: Session, project: Any, actor: User, payload: StateMachineDiagramCreate,
) -> ArchitectureStateMachineDiagram:
    """Creates a state machine diagram (`draft`, or `active` with `activate`, which the checks then gate). The caller
    commits, so a refused activation stores nothing.

    Raises:
        RuleError: 400 for an element the person cannot use; `ActivationRefused` (409) when `activate` is set, since a
            new diagram has no initial state.
    """
    _check_new_element(db, Viewer.of_user(actor, project), [payload.element_id])
    diagram = ArchitectureStateMachineDiagram(
        project_id=project.id,
        unique_code=generate_unique_code(db, project, STATE_MACHINE_ARTEFACT_TYPE, STATE_MACHINE_CODE_PREFIX),
        name=payload.name.strip(), description=payload.description, element_id=payload.element_id,
        status=RecordStatus.DRAFT.value, version=1, creator_id=actor.id, is_archived=False,
    )
    db.add(diagram)
    db.flush()
    if payload.activate:
        require_sound(db, diagram)
        diagram.status = RecordStatus.ACTIVE.value
        db.flush()
    _audit_machine(db, diagram.id, "created", actor, project.id, unique_code=diagram.unique_code, status=diagram.status)
    return diagram


def update_state_machine(
    db: Session, project: Any, actor: User, diagram_id: uuid.UUID, payload: StateMachineDiagramUpdate,
) -> ArchitectureStateMachineDiagram:
    """Applies the fields the body names. The caller commits.

    Raises:
        RuleError: 404 if absent, 409 on a stale `version`, 400 for an element the person cannot use.
    """
    viewer = Viewer.of_user(actor, project)
    diagram = get_state_machine(db, viewer, project.id, diagram_id, lock=True)
    _check_version(diagram, payload.version)
    changes: dict[str, Any] = {}
    if payload.name is not None and payload.name.strip() != diagram.name:
        changes["name"] = payload.name.strip()
    if payload.description is not None and payload.description != diagram.description:
        changes["description"] = payload.description
    if payload.element_id is not None and payload.element_id != diagram.element_id:
        _check_new_element(db, viewer, [payload.element_id])
        changes["element_id"] = payload.element_id
    if payload.line_hops is not None and payload.line_hops != diagram.line_hops:
        changes["line_hops"] = payload.line_hops
    if payload.line_shape is not None and payload.line_shape.value != diagram.line_shape:
        changes["line_shape"] = payload.line_shape.value
    if not changes:
        return diagram
    _touch(diagram, **changes)
    db.flush()
    _audit_machine(db, diagram.id, "updated", actor, project.id, fields=sorted(changes))
    return diagram


def change_state_machine_status(
    db: Session, project: Any, actor: User, diagram_id: uuid.UUID, version: int, status: RecordStatus,
) -> ArchitectureStateMachineDiagram:
    """Moves the diagram to `status`; the move to `active` needs a diagram without an error issue. The caller commits.

    Raises:
        RuleError: 404 if absent, 409 on a stale version, a move the map does not allow, or (`ActivationRefused`) errors.
    """
    diagram = get_state_machine(db, Viewer.of_user(actor, project), project.id, diagram_id, lock=True)
    _check_version(diagram, version)
    refusal = move_refusal(diagram.status, status)
    if refusal:
        raise RuleError(refusal, 409)
    if status == RecordStatus.ACTIVE:
        require_sound(db, diagram)
    previous = diagram.status
    _touch(diagram, status=status.value)
    db.flush()
    _audit_machine(db, diagram.id, "status_changed", actor, project.id, previous=previous, status=status.value)
    return diagram


def set_state_machine_archived(
    db: Session, project: Any, actor: User, diagram_id: uuid.UUID, archived: bool,
) -> ArchitectureStateMachineDiagram:
    """Archives or unarchives a diagram. The caller commits.

    Raises:
        RuleError: 404 if absent.
    """
    diagram = get_state_machine(db, Viewer.of_user(actor, project), project.id, diagram_id, lock=True)
    if diagram.is_archived == archived:
        return diagram
    diagram.is_archived = archived
    diagram.archived_at = datetime.now(UTC) if archived else None
    diagram.archived_by = actor.id if archived else None
    diagram.version += 1
    db.flush()
    _audit_machine(db, diagram.id, "archived" if archived else "unarchived", actor, project.id)
    return diagram


def delete_state_machine(db: Session, project: Any, actor: User, diagram_id: uuid.UUID) -> None:
    """Deletes a diagram with its states and transitions (a database cascade) and the links, tags, places and comments
    that name it or one of its states. The element described is untouched. The caller commits.

    Raises:
        RuleError: 404 if absent.
    """
    diagram = get_state_machine(db, Viewer.of_user(actor, project), project.id, diagram_id, lock=True)
    for state_id in db.scalars(select(ArchitectureState.id).where(ArchitectureState.state_machine_diagram_id == diagram.id)):
        _forget(db, STATE_ARTEFACT_TYPE, state_id)
    _forget(db, STATE_MACHINE_ARTEFACT_TYPE, diagram.id)
    db.delete(diagram)
    db.flush()
    _audit_machine(db, diagram.id, "deleted", actor, project.id)


# --- States ----------------------------------------------------------------


def _depth(parents: dict[uuid.UUID, uuid.UUID | None], state_id: uuid.UUID | None) -> int:
    """How deep the state sits (a top-level state is 1); a cycle in `parents` ends the walk past the cap."""
    depth = 0
    while state_id is not None and depth <= MAX_STATE_DEPTH + 1:
        depth += 1
        state_id = parents.get(state_id)
    return depth


def _check_tree(states: Iterable[ArchitectureState], parents: dict[uuid.UUID, uuid.UUID | None]) -> None:
    """Checks a proposed parent map: every parent is an ordinary state of the diagram, there is no cycle, and no state is
    deeper than `MAX_STATE_DEPTH`.

    Raises:
        RuleError: 400 otherwise.
    """
    by_id = {s.id: s for s in states}
    for state_id, parent in parents.items():
        if parent is None:
            continue
        if parent not in by_id:
            raise RuleError("The parent state is not a state of this state machine diagram.", 400)
        if by_id[parent].kind != StateKind.STATE.value:
            raise RuleError("Only an ordinary state can contain other states.", 400)
        seen = {state_id}
        walker: uuid.UUID | None = parent
        while walker is not None:
            if walker in seen:
                raise RuleError("A state cannot be nested inside itself.", 400)
            seen.add(walker)
            walker = parents.get(walker)
    if any(_depth(parents, s) > MAX_STATE_DEPTH for s in parents):
        raise RuleError(f"States can be nested at most {MAX_STATE_DEPTH} levels deep.", 400)


def _check_name(db: Session, diagram_id: uuid.UUID, name: str, own_id: uuid.UUID | None = None) -> None:
    """Raises a 400 when another state of the diagram has the name (compared without regard to case)."""
    query = select(ArchitectureState.id).where(
        ArchitectureState.state_machine_diagram_id == diagram_id, func.lower(ArchitectureState.name) == name.lower(),
    )
    if own_id is not None:
        query = query.where(ArchitectureState.id != own_id)
    if db.scalar(query.limit(1)) is not None:
        raise RuleError("A state with that name already exists in this state machine diagram.", 400)


def add_state(
    db: Session, project: Any, actor: User, diagram_id: uuid.UUID, payload: StateCreate,
) -> ArchitectureState:
    """Adds a state to the diagram. The caller commits.

    Raises:
        RuleError: 404 if the diagram is absent, 409 on a stale `version`, 400 for a duplicate name or a parent that
            breaks the nesting rules.
    """
    diagram = get_state_machine(db, Viewer.of_user(actor, project), project.id, diagram_id, lock=True)
    _check_version(diagram, payload.version)
    name = payload.name.strip()
    _check_name(db, diagram.id, name)
    label = _clean_label(payload.label, payload.kind.value)
    _check_label_position(payload.label_position.value, payload.kind.value)
    existing = states_of(db, diagram.id)
    state = ArchitectureState(
        state_machine_diagram_id=diagram.id, project_id=project.id,
        unique_code=generate_unique_code(db, project, STATE_ARTEFACT_TYPE, STATE_CODE_PREFIX),
        name=name, description=payload.description, kind=payload.kind.value, parent_state_id=payload.parent_state_id,
        entry_action=payload.entry_action, exit_action=payload.exit_action, activity=payload.activity,
        label=label, label_position=payload.label_position.value, x=payload.x, y=payload.y, width=payload.width,
        height=payload.height, collapsed=payload.collapsed,
        creator_id=actor.id,
    )
    db.add(state)
    db.flush()
    _check_tree([*existing, state], {**{s.id: s.parent_state_id for s in existing}, state.id: state.parent_state_id})
    diagram.version += 1
    db.flush()
    _audit_state(db, state.id, "created", actor, project.id, unique_code=state.unique_code, kind=state.kind)
    _audit_machine(db, diagram.id, "updated", actor, project.id, fields=["states"], state_added=str(state.id))
    return state


_STATE_FIELDS = (
    "name", "description", "kind", "parent_state_id", "entry_action", "exit_action", "activity", "label", "label_position", "x",
    "y", "width", "height", "collapsed",
)


def _clean_label(label: str, kind: str) -> str:
    """The symbol label to store: trimmed, and only for an initial, final or choice state (an ordinary state's name is
    drawn in its box, so a label there would never be seen).

    Raises:
        RuleError: 400 when a label is given for an ordinary state.
    """
    label = label.strip()
    if label and kind == StateKind.STATE.value:
        raise RuleError("Only an initial, final or choice state can carry a symbol label.", 400)
    return label


def _check_label_position(position: str, kind: str) -> None:
    """Refuses a label position other than `inside` for an ordinary state (its name is drawn in its box, so there is no
    symbol to place a label beside).

    Raises:
        RuleError: 400 when an ordinary state is given a position outside the symbol.
    """
    if position != LabelPosition.INSIDE.value and kind == StateKind.STATE.value:
        raise RuleError("Only an initial, final or choice state can place its symbol label.", 400)


def update_state(
    db: Session, project: Any, actor: User, state_id: uuid.UUID, payload: StateUpdate,
) -> ArchitectureState:
    """Applies the fields the body names to a state. The caller commits.

    Raises:
        RuleError: 404 if absent, 409 on a stale `version`, 400 for a duplicate name, a marker that has child states, or
            a parent that breaks the nesting rules.
    """
    viewer = Viewer.of_user(actor, project)
    state, found = get_state(db, viewer, project.id, state_id)
    diagram = get_state_machine(db, viewer, project.id, found.id, lock=True)
    _check_version(diagram, payload.version)
    given = payload.model_fields_set - {"version"}
    changes: dict[str, Any] = {}
    for field in _STATE_FIELDS:
        if field not in given:
            continue
        value = getattr(payload, field)
        if field == "name":
            if value is None:
                continue
            value = value.strip()
            if value.lower() != state.name.lower():
                _check_name(db, diagram.id, value, state.id)
        elif field == "kind":
            if value is None:
                continue
            value = value.value
        elif field == "label":
            if value is None:
                continue
            value = value.strip()
        elif field == "label_position":
            if value is None:
                continue
            value = value.value
        elif value is None and field != "parent_state_id":
            continue
        if value != getattr(state, field):
            changes[field] = value
    kind_after = changes.get("kind", state.kind)
    if kind_after == StateKind.STATE.value and state.label and "label" not in changes:
        changes["label"] = ""  # an ordinary state has no symbol, so the label goes with the kind
    if kind_after == StateKind.STATE.value and state.label_position != LabelPosition.INSIDE.value and "label_position" not in changes:
        changes["label_position"] = LabelPosition.INSIDE.value  # the position goes with the label when the kind becomes ordinary
    if changes.get("label"):
        _clean_label(changes["label"], kind_after)
    if "label_position" in changes:
        _check_label_position(changes["label_position"], kind_after)
    if not changes:
        return state
    if changes.get("kind") in _MARKERS and db.scalar(
        select(ArchitectureState.id).where(ArchitectureState.parent_state_id == state.id).limit(1)
    ):
        raise RuleError("A state that contains other states must stay an ordinary state.", 400)
    existing = states_of(db, diagram.id)
    if "parent_state_id" in changes:
        parents = {s.id: s.parent_state_id for s in existing}
        parents[state.id] = changes.get("parent_state_id", state.parent_state_id)
        _check_tree(existing, parents)
    for key, value in changes.items():
        setattr(state, key, value)
    diagram.version += 1
    db.flush()
    _audit_state(db, state.id, "updated", actor, project.id, fields=sorted(changes))
    _audit_machine(db, diagram.id, "updated", actor, project.id, fields=["states"], state_changed=str(state.id))
    return state


def impact_of_state(db: Session, state: ArchitectureState) -> dict[str, int]:
    """What deleting the state takes with it: its transitions and the links that name it (for the confirmation)."""
    from app.services.relationships import get_all_links

    transitions = db.scalar(select(func.count()).select_from(ArchitectureTransition).where(
        (ArchitectureTransition.source_state_id == state.id) | (ArchitectureTransition.target_state_id == state.id)
    )) or 0
    return {"transitions": transitions, "links": len(get_all_links(db, STATE_ARTEFACT_TYPE, state.id, include_cross_project=True))}


def delete_state(db: Session, project: Any, actor: User, state_id: uuid.UUID, version: int) -> dict[str, int]:
    """Deletes a state, its transitions (a database cascade) and the links, tags and comments that name it. The caller
    commits. Returns what went with it (`impact_of_state`) and the diagram's new `version`.

    Raises:
        RuleError: 404 if absent, 409 on a stale `version` or while the state contains other states.
    """
    viewer = Viewer.of_user(actor, project)
    state, found = get_state(db, viewer, project.id, state_id)
    diagram = get_state_machine(db, viewer, project.id, found.id, lock=True)
    _check_version(diagram, version)
    if db.scalar(select(ArchitectureState.id).where(ArchitectureState.parent_state_id == state.id).limit(1)):
        raise RuleError("This state contains other states; move or delete them first.", 409)
    impact = impact_of_state(db, state)
    _forget(db, STATE_ARTEFACT_TYPE, state.id)
    db.delete(state)
    diagram.version += 1
    db.flush()
    _audit_state(db, state.id, "deleted", actor, project.id, **impact)
    _audit_machine(db, diagram.id, "updated", actor, project.id, fields=["states"], state_removed=str(state.id))
    return {**impact, "version": diagram.version}


# --- Transitions -----------------------------------------------------------


def _own_states(db: Session, diagram_id: uuid.UUID, *state_ids: uuid.UUID) -> None:
    """Raises a 400 unless every state belongs to the diagram."""
    wanted = set(state_ids)
    found = set(db.scalars(select(ArchitectureState.id).where(
        ArchitectureState.id.in_(wanted), ArchitectureState.state_machine_diagram_id == diagram_id,
    )))
    if found != wanted:
        raise RuleError("A transition joins states of its own state machine diagram.", 400)


def add_transition(
    db: Session, project: Any, actor: User, diagram_id: uuid.UUID, payload: TransitionIn,
) -> ArchitectureTransition:
    """Adds a transition. The caller commits.

    Raises:
        RuleError: 404 if the diagram is absent, 409 on a stale `version`, 400 when a state is missing or belongs to
            another diagram.
    """
    diagram = get_state_machine(db, Viewer.of_user(actor, project), project.id, diagram_id, lock=True)
    _check_version(diagram, payload.version)
    if payload.source_state_id is None or payload.target_state_id is None:
        raise RuleError("A transition needs a source state and a target state.", 400)
    _own_states(db, diagram.id, payload.source_state_id, payload.target_state_id)
    count = db.scalar(select(func.count()).select_from(ArchitectureTransition).where(
        ArchitectureTransition.state_machine_diagram_id == diagram.id
    )) or 0
    transition = ArchitectureTransition(
        state_machine_diagram_id=diagram.id, source_state_id=payload.source_state_id,
        target_state_id=payload.target_state_id, event=(payload.event or "").strip(), guard=(payload.guard or "").strip(),
        action=(payload.action or "").strip(), description=payload.description or "", sort_order=count,
        source_point=payload.source_point.value if payload.source_point else None,
        target_point=payload.target_point.value if payload.target_point else None,
        points=[{"x": p.x, "y": p.y} for p in payload.points or []],
        line_shape=payload.line_shape.value if payload.line_shape else None,
    )
    db.add(transition)
    diagram.version += 1
    db.flush()
    _audit_machine(db, diagram.id, "updated", actor, project.id, fields=["transitions"], transition_added=str(transition.id))
    return transition


def _get_transition(db: Session, diagram_id: uuid.UUID, transition_id: uuid.UUID) -> ArchitectureTransition:
    transition = db.scalar(select(ArchitectureTransition).where(
        ArchitectureTransition.id == transition_id, ArchitectureTransition.state_machine_diagram_id == diagram_id,
    ))
    if transition is None:
        raise RuleError("Transition not found.", 404)
    return transition


def update_transition(
    db: Session, project: Any, actor: User, diagram_id: uuid.UUID, transition_id: uuid.UUID, payload: TransitionIn,
) -> ArchitectureTransition:
    """Applies the fields the body names to a transition. The caller commits.

    Raises:
        RuleError: 404 if absent, 409 on a stale `version`, 400 when a state belongs to another diagram.
    """
    diagram = get_state_machine(db, Viewer.of_user(actor, project), project.id, diagram_id, lock=True)
    _check_version(diagram, payload.version)
    transition = _get_transition(db, diagram.id, transition_id)
    given = payload.model_fields_set - {"version"}
    changes: dict[str, Any] = {}
    for field in ("source_state_id", "target_state_id", "event", "guard", "action", "description"):
        value = getattr(payload, field)
        if field in given and value is not None:
            value = value.strip() if isinstance(value, str) and field != "description" else value
            if value != getattr(transition, field):
                changes[field] = value
    for field in ("source_point", "target_point"):
        if field in given:
            value = getattr(payload, field)
            value = value.value if value else None
            if value != getattr(transition, field):
                changes[field] = value
    if "points" in given and payload.points is not None:
        points = [{"x": p.x, "y": p.y} for p in payload.points]
        if points != transition.points:
            changes["points"] = points
    if "line_shape" in given:
        shape = payload.line_shape.value if payload.line_shape else None
        if shape != transition.line_shape:
            changes["line_shape"] = shape
    if not changes:
        return transition
    _own_states(
        db, diagram.id, changes.get("source_state_id", transition.source_state_id),
        changes.get("target_state_id", transition.target_state_id),
    )
    for key, value in changes.items():
        setattr(transition, key, value)
    diagram.version += 1
    db.flush()
    _audit_machine(db, diagram.id, "updated", actor, project.id, fields=["transitions"], transition_changed=str(transition.id))
    return transition


def delete_transition(
    db: Session, project: Any, actor: User, diagram_id: uuid.UUID, transition_id: uuid.UUID, version: int,
) -> int:
    """Deletes a transition and returns the diagram's new `version`. The caller commits.

    Raises:
        RuleError: 404 if absent, 409 on a stale `version`.
    """
    diagram = get_state_machine(db, Viewer.of_user(actor, project), project.id, diagram_id, lock=True)
    _check_version(diagram, version)
    transition = _get_transition(db, diagram.id, transition_id)
    db.delete(transition)
    diagram.version += 1
    db.flush()
    _audit_machine(db, diagram.id, "updated", actor, project.id, fields=["transitions"], transition_removed=str(transition_id))
    return diagram.version


# --- Layout ----------------------------------------------------------------


def _check_note_leaders(
    notes: Sequence[NoteIn], stored: dict[uuid.UUID, list[ArchitectureNoteLeader]], states: set[uuid.UUID],
    transitions: set[uuid.UUID],
) -> None:
    """Checks what the notes' leaders point at: a state or transition of this diagram, or a point (a note on a state machine
    diagram never points at a block diagram's element or connection). A leader id must be one of its own note's and listed
    once.

    Raises:
        RuleError: 400 for a leader to an element or connection, to a state or transition of another diagram, or one that is
            not the note's own or is listed twice.
    """
    for note in notes:
        own = {row.id for row in stored.get(note.id, [])} if note.id is not None else set()
        seen: set[uuid.UUID] = set()
        for leader in note.leaders:
            if leader.id is not None:
                if leader.id not in own or leader.id in seen:
                    raise RuleError("A leader does not belong to this note, or is listed twice.", 400)
                seen.add(leader.id)
            if leader.kind in (LeaderKind.ELEMENT, LeaderKind.CONNECTION):
                raise RuleError("A note on a state machine diagram points at a state, a transition or a point.", 400)
            if leader.kind == LeaderKind.STATE and leader.state_id not in states:
                raise RuleError("A note can point at a state of its own state machine diagram.", 400)
            if leader.kind == LeaderKind.TRANSITION and leader.transition_id not in transitions:
                raise RuleError("A note can point at a transition of its own state machine diagram.", 400)


def save_layout(
    db: Session, project: Any, actor: User, diagram_id: uuid.UUID, payload: StateMachineLayoutSave,
) -> ArchitectureStateMachineDiagram:
    """Replaces the boxes and nesting of the states named, the attach points of the transitions named and, when the request
    carries them, the diagram's notes with their leaders (the editor's save). Anything not named is kept. The caller commits.

    Raises:
        RuleError: 404 if absent, 409 on a stale `version`, 400 for a state or transition of another diagram, a note or leader
            that is not this diagram's or points outside it, or a nesting that breaks the rules.
    """
    diagram = get_state_machine(db, Viewer.of_user(actor, project), project.id, diagram_id, lock=True)
    _check_version(diagram, payload.version)
    states = {s.id: s for s in states_of(db, diagram.id)}
    transitions = {t.id: t for t in transitions_of(db, diagram.id)}
    if any(s.id not in states for s in payload.states) or any(t.id not in transitions for t in payload.transitions):
        raise RuleError("A state or transition does not belong to this state machine diagram.", 400)
    notes_changed = 0
    if payload.notes is not None:
        notes_changed = sync_notes(
            db, payload.notes, machine_notes_of(db, diagram.id),
            lambda: ArchitectureDiagramNote(id=uuid.uuid4(), state_machine_diagram_id=diagram.id),
            lambda notes, stored: _check_note_leaders(notes, stored, set(states), set(transitions)),
        )
    parents = {i: s.parent_state_id for i, s in states.items()}
    parents.update({s.id: s.parent_state_id for s in payload.states})
    _check_tree(states.values(), parents)
    changed = notes_changed
    for given in payload.states:
        row = states[given.id]
        values = (given.x, given.y, given.width, given.height, given.collapsed, given.parent_state_id)
        if values != (row.x, row.y, row.width, row.height, row.collapsed, row.parent_state_id):
            row.x, row.y, row.width, row.height, row.collapsed, row.parent_state_id = values
            changed += 1
    for given_t in payload.transitions:
        t = transitions[given_t.id]
        points = (given_t.source_point.value if given_t.source_point else None, given_t.target_point.value if given_t.target_point else None)
        if points != (t.source_point, t.target_point):
            t.source_point, t.target_point = points
            changed += 1
        if given_t.points is not None:
            route = [{"x": p.x, "y": p.y} for p in given_t.points]
            if route != t.points:
                t.points = route
                changed += 1
        if "line_shape" in given_t.model_fields_set:
            shape = given_t.line_shape.value if given_t.line_shape else None
            if shape != t.line_shape:
                t.line_shape = shape
                changed += 1
    if changed:
        diagram.version += 1
        db.flush()
        _audit_machine(db, diagram.id, "layout_saved", actor, project.id, changed=changed)
    return diagram


# --- Reading ---------------------------------------------------------------


def issue_out(issue: checks.ValidationIssue) -> ValidationIssueOut:
    """An issue as the API gives it."""
    return ValidationIssueOut(severity=issue.severity, code=issue.code, subject=issue.subject, message=issue.message)


def _element_info(db: Session, viewer: Viewer, element_ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, tuple[str, str]]:
    """`{element id: (code, name)}` for the elements, the name blank for one the viewer may not read."""
    ids = set(element_ids)
    if not ids:
        return {}
    readable = visible_element_ids(db, viewer, ids)
    return {
        e.id: (e.unique_code, e.name if e.id in readable else "")
        for e in db.scalars(select(ArchitectureElement).where(ArchitectureElement.id.in_(ids)))
    }


def state_machine_outs(
    db: Session, diagrams: Sequence[ArchitectureStateMachineDiagram], viewer: Viewer,
) -> list[StateMachineDiagramOut]:
    """API shapes for `diagrams`: state and transition counts, validation counts and elements are read in bulk, so the cost
    does not grow with the list."""
    ids = [d.id for d in diagrams]

    def counts(model: Any) -> dict[uuid.UUID, int]:
        if not ids:
            return {}
        return dict(db.execute(
            select(model.state_machine_diagram_id, func.count()).where(model.state_machine_diagram_id.in_(ids))
            .group_by(model.state_machine_diagram_id)
        ).tuples().all())

    state_counts, transition_counts = counts(ArchitectureState), counts(ArchitectureTransition)
    found = checks.validation_by_diagram(db, ids)
    elements = _element_info(db, viewer, (d.element_id for d in diagrams))
    out: list[StateMachineDiagramOut] = []
    for d in diagrams:
        code, name = elements.get(d.element_id, (None, None))
        issues = found.get(d.id, [])
        out.append(StateMachineDiagramOut(
            id=d.id, project_id=d.project_id, unique_code=d.unique_code, name=d.name, description=d.description,
            element_id=d.element_id, element_code=code, element_name=name, line_hops=d.line_hops, line_shape=LineShape(d.line_shape), status=d.status,
            allowed_status_moves=allowed_moves(d.status), version=d.version, creator_id=d.creator_id,
            is_archived=d.is_archived, archived_at=d.archived_at, created_at=d.created_at, updated_at=d.updated_at,
            state_count=state_counts.get(d.id, 0), transition_count=transition_counts.get(d.id, 0),
            error_count=sum(1 for f in issues if f.severity == ValidationSeverity.ERROR),
            warning_count=sum(1 for f in issues if f.severity == ValidationSeverity.WARNING),
        ))
    return out


def state_outs(db: Session, states: Sequence[ArchitectureState], viewer: Viewer) -> list[StateOut]:
    """API shapes for `states`: their diagrams, elements and parents are read in bulk."""
    diagram_ids = {s.state_machine_diagram_id for s in states}
    diagrams = {
        d.id: d for d in db.scalars(select(ArchitectureStateMachineDiagram).where(ArchitectureStateMachineDiagram.id.in_(diagram_ids)))
    } if diagram_ids else {}
    elements = _element_info(db, viewer, (d.element_id for d in diagrams.values()))
    parent_codes = {
        i: code for i, code in db.execute(
            select(ArchitectureState.id, ArchitectureState.unique_code).where(
                ArchitectureState.id.in_({s.parent_state_id for s in states if s.parent_state_id})
            )
        ).tuples()
    } if any(s.parent_state_id for s in states) else {}
    out: list[StateOut] = []
    for s in states:
        d = diagrams[s.state_machine_diagram_id]
        code, name = elements.get(d.element_id, (None, None))
        out.append(StateOut(
            id=s.id, project_id=s.project_id, unique_code=s.unique_code, state_machine_diagram_id=d.id,
            state_machine_diagram_code=d.unique_code, state_machine_diagram_name=d.name,
            state_machine_diagram_version=d.version, element_id=d.element_id,
            element_code=code, element_name=name, name=s.name, description=s.description, kind=s.kind,
            parent_state_id=s.parent_state_id, parent_state_code=parent_codes.get(s.parent_state_id) if s.parent_state_id else None,
            entry_action=s.entry_action, exit_action=s.exit_action, activity=s.activity, label=s.label,
            label_position=s.label_position, x=s.x, y=s.y, width=s.width,
            height=s.height, collapsed=s.collapsed, status=d.status, is_archived=d.is_archived, creator_id=s.creator_id,
            created_at=s.created_at, updated_at=s.updated_at,
        ))
    return out


def transition_outs(
    transitions: Sequence[ArchitectureTransition], states: Sequence[ArchitectureState], diagram_version: int,
) -> list[TransitionOut]:
    """API shapes for `transitions`, naming each end by the code of the state (`states` holds the diagram's states) and
    carrying the diagram's current version."""
    codes = {s.id: s.unique_code for s in states}
    return [
        TransitionOut(
            id=t.id, state_machine_diagram_id=t.state_machine_diagram_id, state_machine_diagram_version=diagram_version,
            source_state_id=t.source_state_id,
            source_state_code=codes.get(t.source_state_id, ""), target_state_id=t.target_state_id,
            target_state_code=codes.get(t.target_state_id, ""), event=t.event, guard=t.guard, action=t.action,
            description=t.description, sort_order=t.sort_order,
            source_point=AttachPoint(t.source_point) if t.source_point else None,
            target_point=AttachPoint(t.target_point) if t.target_point else None,
            points=[WaypointIn(x=p["x"], y=p["y"]) for p in t.points],
            line_shape=LineShape(t.line_shape) if t.line_shape else None,
        )
        for t in transitions
    ]


def model_of(db: Session, diagram: ArchitectureStateMachineDiagram, viewer: Viewer) -> StateMachineModel:
    """The diagram with its states, transitions and validation issues, for the editor and the outline."""
    states, transitions = states_of(db, diagram.id), transitions_of(db, diagram.id)
    notes = machine_notes_of(db, diagram.id)
    leaders = leaders_of(db, (n.id for n in notes))
    return StateMachineModel(
        diagram=state_machine_outs(db, [diagram], viewer)[0], states=state_outs(db, states, viewer),
        transitions=transition_outs(transitions, states, diagram.version),
        notes=[note_out(n, leaders.get(n.id, ())) for n in notes], validation=[issue_out(f) for f in checks.check(states, transitions)],
    )


def filter_state_machines(
    rows: list[ArchitectureStateMachineDiagram], *, status_: str | None = None, open_only: bool = False,
    search: str | None = None, element_id: uuid.UUID | None = None,
) -> list[ArchitectureStateMachineDiagram]:
    """The diagrams the list's filters keep. `open_only` leaves out retired and rejected diagrams."""
    from app.modules.architecture.labels import INACTIVE_STATUSES
    from app.modules.architecture.record_routes import _matches

    return [
        d for d in rows
        if (status_ is None or d.status == status_)
        and (not open_only or d.status not in INACTIVE_STATUSES)
        and (element_id is None or d.element_id == element_id)
        and _matches(search, d.unique_code, d.name, d.description)
    ]


def grouped_states(states: Iterable[ArchitectureState]) -> dict[uuid.UUID, list[ArchitectureState]]:
    """The states by diagram id."""
    grouped: dict[uuid.UUID, list[ArchitectureState]] = defaultdict(list)
    for s in states:
        grouped[s.state_machine_diagram_id].append(s)
    return grouped
