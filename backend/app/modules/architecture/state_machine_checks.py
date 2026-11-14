"""
Module: modules.architecture.state_machine_checks

The modelling checks of a state machine diagram: one function that returns every finding, read by the API (the editor,
the outline and the lists) and by the activation gate, so there is no second implementation in the browser.

Responsibilities:
- Return findings of two severities. An error blocks the move to `active` (an active state machine diagram with no
  single initial state, or with arrows the notation forbids, cannot be read unambiguously by the requirements and
  decisions that cite it); a warning never blocks.
- Read the findings of many diagrams in two statements (`findings_by_diagram`), so a list stays flat.

Design decisions:
- The checks are a pure function of the states and transitions (`check`): no database access and no person, so the
  result is the same wherever it is computed.
- A finding names its subject by state code (a transition's finding names its source state), never by a name or text.
- With no top-level initial state the diagram has no entry point, so reachability is not reported (the error already
  says so and every state would otherwise be a warning).

Dependencies: this module's models and enums only.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.architecture.enums import FindingSeverity, StateKind
from app.modules.architecture.models import ArchitectureState, ArchitectureTransition


@dataclass(frozen=True)
class Finding:
    """One modelling finding.

    Attributes:
        severity: Whether it blocks activation.
        code: A stable key (`no_initial`, `unreachable`, ...).
        subject: The code of the state it concerns, or an empty string for the diagram as a whole.
        message: The sentence shown to a person.
    """

    severity: FindingSeverity
    code: str
    subject: str
    message: str


def _error(code: str, subject: str, message: str) -> Finding:
    return Finding(FindingSeverity.ERROR, code, subject, message)


def _warning(code: str, subject: str, message: str) -> Finding:
    return Finding(FindingSeverity.WARNING, code, subject, message)


def _reachable(
    states: dict[uuid.UUID, ArchitectureState], children: dict[uuid.UUID | None, list[uuid.UUID]],
    outgoing: dict[uuid.UUID, list[uuid.UUID]], parents: dict[uuid.UUID, uuid.UUID | None],
) -> set[uuid.UUID]:
    """The states entered when the machine runs from its top-level initial state: along transitions, into a composite
    state's own initial state, and into every composite state that contains an entered one."""
    seen: set[uuid.UUID] = set()
    queue = [i for i in children.get(None, []) if states[i].kind == StateKind.INITIAL.value]
    while queue:
        current = queue.pop()
        if current in seen:
            continue
        seen.add(current)
        queue.extend(outgoing.get(current, []))
        queue.extend(i for i in children.get(current, []) if states[i].kind == StateKind.INITIAL.value)
        parent = parents.get(current)
        if parent is not None:
            queue.append(parent)
    return seen


def _has_exit(state_id: uuid.UUID, descendants: set[uuid.UUID], transitions: Sequence[ArchitectureTransition]) -> bool:
    """Whether the state can be left: a transition starts at it, or at a nested state and ends outside the state."""
    inside = descendants | {state_id}
    return any(
        t.source_state_id == state_id or (t.source_state_id in descendants and t.target_state_id not in inside)
        for t in transitions
    )


def _descendants(children: dict[uuid.UUID | None, list[uuid.UUID]], root: uuid.UUID) -> set[uuid.UUID]:
    found: set[uuid.UUID] = set()
    stack = list(children.get(root, []))
    while stack:
        current = stack.pop()
        if current not in found:
            found.add(current)
            stack.extend(children.get(current, []))
    return found


def check(states: Sequence[ArchitectureState], transitions: Sequence[ArchitectureTransition]) -> list[Finding]:
    """Every finding for one state machine diagram, errors first, each group in state code order.

    Args:
        states: The diagram's states.
        transitions: The diagram's transitions.

    Returns:
        The findings (empty when the diagram is sound).
    """
    by_id = {s.id: s for s in states}
    children: dict[uuid.UUID | None, list[uuid.UUID]] = defaultdict(list)
    parents: dict[uuid.UUID, uuid.UUID | None] = {}
    for s in sorted(states, key=lambda s: s.unique_code):
        children[s.parent_state_id if s.parent_state_id in by_id else None].append(s.id)
        parents[s.id] = s.parent_state_id if s.parent_state_id in by_id else None
    incoming: dict[uuid.UUID, int] = defaultdict(int)
    outgoing: dict[uuid.UUID, list[uuid.UUID]] = defaultdict(list)
    errors: list[Finding] = []
    valid: list[ArchitectureTransition] = []
    for t in transitions:
        if t.source_state_id not in by_id or t.target_state_id not in by_id:
            errors.append(_error("transition_outside", "", "A transition ends at a state outside this state machine diagram."))
            continue
        valid.append(t)
        incoming[t.target_state_id] += 1
        outgoing[t.source_state_id].append(t.target_state_id)

    top_initial = [i for i in children.get(None, []) if by_id[i].kind == StateKind.INITIAL.value]
    if not top_initial:
        errors.append(_error("no_initial", "", "The state machine diagram has no initial state at the top level."))
    for parent, ids in children.items():
        initials = [i for i in ids if by_id[i].kind == StateKind.INITIAL.value]
        if len(initials) > 1:
            where = "at the top level" if parent is None else f"in {by_id[parent].unique_code}"
            errors.append(_error(
                "multiple_initial", by_id[initials[1]].unique_code, f"More than one initial state exists {where}.",
            ))
    for s in sorted(states, key=lambda s: s.unique_code):
        if s.kind == StateKind.INITIAL.value and incoming.get(s.id):
            errors.append(_error("initial_incoming", s.unique_code, f"{s.unique_code} is an initial state and has an incoming transition."))
        if s.kind == StateKind.FINAL.value and outgoing.get(s.id):
            errors.append(_error("final_outgoing", s.unique_code, f"{s.unique_code} is a final state and has an outgoing transition."))

    warnings: list[Finding] = []
    reached = _reachable(by_id, children, outgoing, parents) if top_initial else None
    for s in sorted(states, key=lambda s: s.unique_code):
        kind, kids = s.kind, children.get(s.id, [])
        if reached is not None and kind != StateKind.INITIAL.value and s.id not in reached:
            warnings.append(_warning("unreachable", s.unique_code, f"{s.unique_code} cannot be reached from the initial state."))
        if kind == StateKind.STATE.value and not _has_exit(s.id, _descendants(children, s.id), valid):
            warnings.append(_warning("no_outgoing", s.unique_code, f"{s.unique_code} has no outgoing transition and is not a final state."))
        if kind == StateKind.CHOICE.value and len(outgoing.get(s.id, [])) < 2:
            warnings.append(_warning("choice_few_outgoing", s.unique_code, f"{s.unique_code} is a choice with fewer than two outgoing transitions."))
        if kids and kind == StateKind.STATE.value and not any(by_id[k].kind == StateKind.INITIAL.value for k in kids):
            warnings.append(_warning("composite_no_initial", s.unique_code, f"{s.unique_code} contains states but has no initial state."))
    seen: set[tuple[uuid.UUID, str]] = set()
    flagged: set[tuple[uuid.UUID, str]] = set()
    for t in valid:
        if t.guard.strip():
            continue
        key = (t.source_state_id, t.event.strip().casefold())
        if key in seen and key not in flagged:
            flagged.add(key)
            code = by_id[t.source_state_id].unique_code
            warnings.append(_warning("ambiguous", code, f"{code} has two transitions with the same event and no guard."))
        seen.add(key)
    return [*errors, *warnings]


def findings_by_diagram(db: Session, diagram_ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, list[Finding]]:
    """The findings of each diagram, reading every diagram's states and transitions in two statements."""
    ids = list(diagram_ids)
    if not ids:
        return {}
    states: dict[uuid.UUID, list[ArchitectureState]] = defaultdict(list)
    for row in db.scalars(select(ArchitectureState).where(ArchitectureState.state_machine_diagram_id.in_(ids))):
        states[row.state_machine_diagram_id].append(row)
    transitions: dict[uuid.UUID, list[ArchitectureTransition]] = defaultdict(list)
    for t in db.scalars(select(ArchitectureTransition).where(ArchitectureTransition.state_machine_diagram_id.in_(ids))):
        transitions[t.state_machine_diagram_id].append(t)
    return {i: check(states.get(i, []), transitions.get(i, [])) for i in ids}
