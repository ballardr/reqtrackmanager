"""
Module: services.lifecycles

The one server rule for the state path of a record type: which optional states a project uses, which an
organisation requires, and which moves are therefore legal.

Responsibilities:
- Resolve the effective configuration of a project for every registered lifecycle (`resolve_project_lifecycles`): the
  project's own choice, else the nearest ancestor project's, else every state on, with the organisation's required
  states added back unless the project is exempt.
- Work out the legal moves from a state with turned-off states stepped over (`effective_moves`) and enforce them
  (`check_move`), so the UI, the API and MCP share one rule; the skipped states come back so a type can still apply
  the checks of a state a move passes over.
- Carry the configuration in project and organisation bundles and to a project made from a template
  (`export_project`, `import_project`, `copy_project`, `export_org`, `import_org`).
- Write the three tiers (`set_project_disabled`, `set_org_required`, `add_exemption`, `remove_exemption`), validating
  against the registered definitions and recording one audit event each (type and state keys only).
- Let one record skip steps of its path (`skip_moves`, and `check_move` when the request carries a skip request): the
  project must allow it, the organisation must not forbid it (an exempt project is not bound), the person must be
  able to enter every step passed over, and a gated or organisation-required step is never passed over.

Design decisions:
- A state is turned off for a project, never deleted: a record already in it stays valid and can move on, and turning
  the state back on restores the path. A move into a turned-off state is refused; the move is offered to its
  successors instead.
- A state a type marks gated or off-path is never optional, so a turned-off state can never remove an approval.
- An organisation requirement beats a project's choice; an exemption (per type, per project, optionally with nested
  children) lifts the requirement for that project only. The project's stored choice is kept, so a requirement later
  removed gives the project's own choice back.
- A skip is one more legal move through the same rule, never a second transition table: the type's own move endpoint
  runs, the skip request (reason, person) rides on the session, and `check_move` accepts the move and records one
  `steps_skipped` audit event naming the steps passed over.
- Resolution reads a few small tables per call and never loops per record; list responses read it once per request.

Dependencies: `modules.registry` (definitions), `services.project_hierarchy` (ancestor chain), `services.audit`.
"""

from __future__ import annotations

import enum
import uuid
from collections import deque
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Literal

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.lifecycle import (
    OrganizationLifecycleExemption,
    OrganizationLifecycleRequirement,
    OrganizationLifecycleSkipExemption,
    OrganizationLifecycleSkipPolicy,
    ProjectLifecycleSetting,
    ProjectLifecycleSkipSetting,
)
from app.models.organization import Organization
from app.models.project import Project
from app.models.user import User
from app.modules.registry import (
    LifecycleDefinition,
    artefact_type_enabled_for_project,
    artefact_type_module,
    get_lifecycles,
    is_module_enabled,
    is_org_module_subcomponent_enabled,
    subcomponent_serving,
)
from app.services.audit import log_event
from app.services.project_hierarchy import get_project_chain_ids

AUDIT_ENTITY_TYPE = "lifecycle_settings"
Source = Literal["project", "parent_project", "default"]

SKIP_REQUEST_KEY = "lifecycle_skip_request"
SKIP_REASON_MAX_LENGTH = 500
SKIP_AUDIT_ACTION = "steps_skipped"


@dataclass(frozen=True)
class SkipRequest:
    """A person's request to move one record past steps of its path, carried on the database session so the type's own
    move endpoint and transition function need no extra parameter.

    Attributes:
        user: The person asking; every step passed over is checked against their rights.
        reason: Why the steps are skipped (recorded on the audit event).
    """

    user: User
    reason: str


@dataclass(frozen=True)
class SkipPolicy:
    """Whether records of a project may skip steps.

    Attributes:
        own: The project's own choice, or `None` when it has none.
        chosen: The project's choice (own, else the nearest ancestor's, else off).
        source: Where `chosen` came from.
        forbidden: Whether the organisation forbids skipping.
        exempt: Whether the organisation's ban does not bind this project.
    """

    own: bool | None
    chosen: bool
    source: Source
    forbidden: bool
    exempt: bool

    @property
    def enforced(self) -> bool:
        """Whether the organisation's ban binds this project."""
        return self.forbidden and not self.exempt

    @property
    def allowed(self) -> bool:
        """Whether a record of the project may skip steps now."""
        return self.chosen and not self.enforced


@dataclass(frozen=True)
class ResolvedLifecycle:
    """One record type's lifecycle as it applies to one project.

    Attributes:
        artefact_type: The registered record type.
        module_key: The module that registered it.
        definition: The type's `LifecycleDefinition`.
        own: The project's own turned-off states, or `None` when the project has no choice of its own.
        chosen: The turned-off states the project's choice resolves to (own, else the nearest ancestor's).
        source: Where `chosen` came from.
        required: The states the organisation requires.
        exempt: Whether the organisation's requirement does not bind this project.
        disabled: The states that are off in this project (`chosen` without the enforced required states).
    """

    artefact_type: str
    module_key: str
    definition: LifecycleDefinition
    own: frozenset[str] | None
    chosen: frozenset[str]
    source: Source
    required: frozenset[str]
    exempt: bool
    disabled: frozenset[str]

    @property
    def enforced(self) -> frozenset[str]:
        """The required states that bind this project (none when it is exempt)."""
        return frozenset() if self.exempt else self.required


def table_from_enum[S: enum.Enum](table: Mapping[S, Iterable[S]]) -> dict[str, frozenset[str]]:
    """A type's enum-keyed transition table as the string-keyed one a `LifecycleDefinition` holds (the type's own
    transition function keeps enforcing the same table, so there is one source)."""
    return {state.value: frozenset(n.value for n in nexts) for state, nexts in table.items()}


def validate_definition(definition: LifecycleDefinition) -> list[str]:
    """Checks a definition's own rules.

    Args:
        definition: The definition to check.

    Returns:
        A message per violation: an optional state that is the first or last of the path, off the path, gated or
        unknown, a gated or path state missing from the table, a move to an unknown state, a gated type without a record
        model that has a creator.
    """
    problems: list[str] = []
    known = set(definition.transitions) | {n for nexts in definition.transitions.values() for n in nexts}
    for state in definition.path:
        if state not in known:
            problems.append(f"path state {state!r} is not in the transitions")
    for state in definition.optional:
        if state not in definition.path[1:-1]:
            problems.append(f"optional state {state!r} must lie strictly inside the path")
        if state in definition.gated:
            problems.append(f"optional state {state!r} is also gated")
    for state in definition.gated:
        if state not in known:
            problems.append(f"gated state {state!r} is not in the transitions")
    for state in known:
        if state not in definition.labels:
            problems.append(f"state {state!r} has no label")
    if definition.gated and (definition.record_model is None or not hasattr(definition.record_model, "creator_id")):
        problems.append("a type with a gated state needs a record_model with a creator_id")
    return problems


def _state_order(definition: LifecycleDefinition) -> dict[str, int]:
    """The position of each state: path states first, in order, then the others by name."""
    order = {state: i for i, state in enumerate(definition.path)}
    for state in sorted(set(definition.transitions) | {n for ns in definition.transitions.values() for n in ns}):
        order.setdefault(state, len(order))
    return order


def effective_moves(
    definition: LifecycleDefinition, disabled: Iterable[str], current: str
) -> dict[str, tuple[str, ...]]:
    """The legal moves from `current` once the `disabled` states are stepped over.

    Args:
        definition: The type's definition.
        disabled: The states that are off.
        current: The record's current state (it may itself be off: a record parked in a turned-off state moves on).

    Returns:
        `{target state: the turned-off states the move passes over, in order}`. A turned-off state is never a target;
        the targets it would have led to are offered instead. Targets are in path order.
    """
    off = frozenset(disabled)
    order = _state_order(definition)
    moves: dict[str, tuple[str, ...]] = {}
    seen = {current}
    queue: deque[tuple[str, tuple[str, ...]]] = deque([(current, ())])
    while queue:
        state, skipped = queue.popleft()
        for nxt in sorted(definition.transitions.get(state, ()), key=lambda s: order.get(s, len(order))):
            if nxt in seen:
                continue
            if nxt in off:
                seen.add(nxt)
                queue.append((nxt, (*skipped, nxt)))
            else:
                moves.setdefault(nxt, skipped)
    return dict(sorted(moves.items(), key=lambda item: order.get(item[0], len(order))))


def effective_transitions(resolved: ResolvedLifecycle) -> dict[str, list[str]]:
    """Every state's legal next states in `resolved`'s project (what the record pages offer).

    Args:
        resolved: A type's lifecycle for a project.

    Returns:
        `{state: [next states]}` over every state of the type, off states included (a record may sit in one).
    """
    states = sorted(resolved.definition.transitions, key=_state_order(resolved.definition).__getitem__)
    return {s: list(effective_moves(resolved.definition, resolved.disabled, s)) for s in states}


def skip_moves(
    definition: LifecycleDefinition, disabled: Iterable[str], enforced: Iterable[str], current: str,
) -> dict[str, tuple[str, ...]]:
    """The later steps of the path a record in `current` may be moved to by skipping steps.

    A skip never passes a gated step or a step the organisation requires: such a step may be the target, nothing
    beyond it is offered. A move the type already allows (`effective_moves`) is not a skip.

    Args:
        definition: The type's definition.
        disabled: The states that are off.
        enforced: The states the organisation requires of this project.
        current: The record's current state; only a state on the main path can skip.

    Returns:
        `{target state: every state the move passes over, turned-off ones included, in order}`, in path order.
    """
    if current not in definition.path:
        return {}
    off = frozenset(disabled)
    stop = frozenset(definition.gated) | frozenset(enforced)
    direct = effective_moves(definition, off, current)
    moves: dict[str, tuple[str, ...]] = {}
    passed: list[str] = []
    for state in definition.path[definition.path.index(current) + 1:]:
        if state in off:
            passed.append(state)
            continue
        if state not in direct:
            moves[state] = tuple(passed)
        if state in stop:
            break
        passed.append(state)
    return moves


def effective_skip_transitions(resolved: ResolvedLifecycle) -> dict[str, dict[str, list[str]]]:
    """Every main-path state's skip moves in `resolved`'s project: `{state: {target: [states passed over]}}`, with no
    entry for a state that has none. Empty for a type that cannot have steps skipped (no `entry_guard`)."""
    definition = resolved.definition
    if definition.entry_guard is None:
        return {}
    out: dict[str, dict[str, list[str]]] = {}
    for state in definition.path:
        moves = skip_moves(definition, resolved.disabled, resolved.enforced, state)
        if moves:
            out[state] = {target: list(passed) for target, passed in moves.items()}
    return out


def resolve_skip_policy(db: Session, project: Project) -> SkipPolicy:
    """Whether records of `project` may skip steps: the project's choice (own, else the nearest ancestor's, else off)
    unless the organisation forbids skipping and the project is not exempt.

    Args:
        db: Active session (read only).
        project: The project.
    """
    chain = get_project_chain_ids(db, project.id)
    rows = {
        row.project_id: row.allowed
        for row in db.scalars(select(ProjectLifecycleSkipSetting).where(ProjectLifecycleSkipSetting.project_id.in_(chain)))
    }
    chosen = False
    source: Source = "default"
    for depth, project_id in enumerate(chain):
        if project_id in rows:
            chosen, source = rows[project_id], "project" if depth == 0 else "parent_project"
            break
    forbidden = bool(db.scalar(
        select(OrganizationLifecycleSkipPolicy.forbidden).where(
            OrganizationLifecycleSkipPolicy.organization_id == project.organization_id
        )
    ))
    exempt = False
    if forbidden:
        exempt = any(
            ex.project_id == project.id or ex.include_children
            for ex in db.scalars(
                select(OrganizationLifecycleSkipExemption).where(
                    OrganizationLifecycleSkipExemption.organization_id == project.organization_id,
                    OrganizationLifecycleSkipExemption.project_id.in_(chain),
                )
            )
        )
    return SkipPolicy(own=rows.get(project.id), chosen=chosen, source=source, forbidden=forbidden, exempt=exempt)


def request_skip(db: Session, user: User, reason: str) -> None:
    """Records on the session that this request moves a record past steps (`check_move` acts on it).

    Args:
        db: The request's session.
        user: The person asking.
        reason: Why; stored on the audit event.

    Raises:
        HTTPException: 400 when the reason is empty or longer than `SKIP_REASON_MAX_LENGTH`.
    """
    text = reason.strip()
    if not text or len(text) > SKIP_REASON_MAX_LENGTH:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"A reason of up to {SKIP_REASON_MAX_LENGTH} characters is required to skip steps.",
        )
    db.info[SKIP_REQUEST_KEY] = SkipRequest(user=user, reason=text)


def resolve_project_lifecycles(db: Session, project: Project) -> dict[str, ResolvedLifecycle]:
    """The effective lifecycle of every registered type for `project`.

    Args:
        db: Active session (read only).
        project: The project.

    Returns:
        `{artefact type: ResolvedLifecycle}` over every registered definition, whether or not its module is enabled.
    """
    definitions = get_lifecycles()
    if not definitions:
        return {}
    chain = get_project_chain_ids(db, project.id)
    rows: dict[tuple[uuid.UUID, str], frozenset[str]] = {
        (row.project_id, row.artefact_type): frozenset(row.disabled_states or [])
        for row in db.scalars(select(ProjectLifecycleSetting).where(ProjectLifecycleSetting.project_id.in_(chain)))
    }
    required: dict[str, set[str]] = {}
    for req in db.scalars(
        select(OrganizationLifecycleRequirement).where(OrganizationLifecycleRequirement.organization_id == project.organization_id)
    ):
        required.setdefault(req.artefact_type, set()).add(req.state)
    exempt_types: set[str] = set()
    for ex in db.scalars(
        select(OrganizationLifecycleExemption).where(
            OrganizationLifecycleExemption.organization_id == project.organization_id,
            OrganizationLifecycleExemption.project_id.in_(chain),
        )
    ):
        if ex.project_id == project.id or ex.include_children:
            exempt_types.add(ex.artefact_type)

    resolved: dict[str, ResolvedLifecycle] = {}
    for artefact_type, (module_key, definition) in definitions.items():
        optional = frozenset(definition.optional)
        own = rows.get((project.id, artefact_type))
        chosen: frozenset[str] = frozenset()
        source: Source = "default"
        for depth, project_id in enumerate(chain):
            found = rows.get((project_id, artefact_type))
            if found is not None:
                chosen, source = found & optional, "project" if depth == 0 else "parent_project"
                break
        needed = frozenset(required.get(artefact_type, ())) & optional
        exempt = artefact_type in exempt_types
        resolved[artefact_type] = ResolvedLifecycle(
            artefact_type=artefact_type, module_key=module_key, definition=definition,
            own=None if own is None else own & optional, chosen=chosen, source=source, required=needed, exempt=exempt,
            disabled=chosen if exempt else chosen - needed,
        )
    return resolved


def lifecycle_for(db: Session, project_id: uuid.UUID, artefact_type: str) -> ResolvedLifecycle:
    """One type's effective lifecycle in a project, for a response that lists legal next states: resolve it once per
    request and project, then read each record's moves from it (`next_states`).

    Raises:
        ValueError: When the project no longer exists.
        KeyError: When the type has no registered lifecycle (a programming error).
    """
    project = db.get(Project, project_id)
    if project is None:
        raise ValueError("The record's project no longer exists.")
    return resolve_project_lifecycles(db, project)[artefact_type]


def next_states(resolved: ResolvedLifecycle, state: str) -> list[str]:
    """The states a record in `state` may move to under `resolved`, in path order."""
    return list(effective_moves(resolved.definition, resolved.disabled, state))


def available_lifecycles(db: Session, project: Project) -> list[ResolvedLifecycle]:
    """The lifecycles a project administrator may configure: those with optional states whose module is enabled for the
    project, in type-name order."""
    resolved = resolve_project_lifecycles(db, project)
    return [
        r for _, r in sorted(resolved.items())
        if r.definition.optional and artefact_type_enabled_for_project(db, r.artefact_type, project.id)
    ]


def _article(label: str) -> str:
    """`a` or `an` for a record type label."""
    return "an" if label[:1].lower() in "aeiou" else "a"


def check_move(
    db: Session, project_id: uuid.UUID | None, artefact_type: str, current: str, target: str,
    *, record_id: uuid.UUID | None = None,
) -> tuple[str, ...]:
    """Enforces a state move in `project_id`.

    A move the path allows is accepted. Otherwise, when the request carries a skip request (`request_skip`), a move to
    a later step of the path is accepted if the project allows skipping, the organisation does not forbid it, no
    gated or required step is passed over and the person may enter every step passed over.

    Args:
        db: Active session (a skip writes one audit event; not committed).
        project_id: The record's project, or `None` for a record the organisation owns, which has no project to
            configure and keeps the type's full path.
        artefact_type: The registered record type.
        current: The record's current state.
        target: The state it is moved to.
        record_id: The record, needed to skip steps (the audit event and the entry checks name it).

    Returns:
        The states the move passes over, in order (turned-off ones, and skipped ones), so the caller can still apply
        the checks of those states.

    Raises:
        ValueError: When the move is not legal here; the message names the states that are.
        HTTPException: 403 when a skip passes over a step the person may not enter.
        KeyError: When the type has no registered lifecycle (a programming error).
    """
    skip_request: SkipRequest | None = db.info.get(SKIP_REQUEST_KEY)
    if project_id is None:
        definition = get_lifecycles()[artefact_type][1]
        disabled: frozenset[str] = frozenset()
        enforced: frozenset[str] = frozenset()
    else:
        resolved = lifecycle_for(db, project_id, artefact_type)
        definition, disabled, enforced = resolved.definition, resolved.disabled, resolved.enforced
    moves = effective_moves(definition, disabled, current)
    if target in moves:
        return moves[target]
    label = definition.label

    def name(state: str) -> str:
        return definition.labels.get(state, state)

    skips: dict[str, tuple[str, ...]] = {}
    if skip_request is not None and project_id is not None and record_id is not None:
        project = db.get(Project, project_id)
        if project is None or not resolve_skip_policy(db, project).allowed:
            raise ValueError("Skipping steps is not allowed in this project.")
        if definition.entry_guard is None:
            raise ValueError(f"Steps cannot be skipped for {_article(label)} {label}.")
        skips = skip_moves(definition, disabled, enforced, current)
        if target in skips:
            passed = skips[target]
            skipped = [state for state in passed if state not in disabled]
            for state in skipped:
                definition.entry_guard(db, skip_request.user, project, record_id, state)
            log_event(
                db, entity_type=artefact_type, entity_id=record_id, action=SKIP_AUDIT_ACTION,
                actor_id=skip_request.user.id, project_id=project_id,
                detail={
                    "from": current, "to": target, "skipped": skipped,
                    "skipped_labels": [name(state) for state in skipped], "reason": skip_request.reason,
                },
            )
            return passed

    head = f"Cannot move {_article(label)} {label} from '{name(current)}' to '{name(target)}'."
    if target in disabled and target in {n for ns in definition.transitions.values() for n in ns}:
        head += f" The state '{name(target)}' is turned off in this project."
    allowed = [*moves, *skips]
    if allowed:
        head += " Allowed next states: " + ", ".join(f"'{name(s)}'" for s in allowed) + "."
    raise ValueError(head)


def _validated_type(artefact_type: str) -> tuple[str, LifecycleDefinition]:
    """The module key and definition of a registered lifecycle.

    Raises:
        HTTPException: 404 for an unknown record type.
    """
    found = get_lifecycles().get(artefact_type)
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown record type.")
    return found


def _validated_states(definition: LifecycleDefinition, states: Iterable[str]) -> list[str]:
    """`states` deduplicated in path order, each an optional state of the type.

    Raises:
        HTTPException: 422 for a state the type does not allow to be turned off or required.
    """
    wanted = set(states)
    unknown = sorted(wanted - set(definition.optional))
    if unknown:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"These states cannot be turned off or required for a {definition.label}: {', '.join(unknown)}.",
        )
    return [s for s in definition.optional if s in wanted]


def set_project_disabled(
    db: Session, *, project: Project, artefact_type: str, disabled: Iterable[str] | None, actor_id: uuid.UUID,
) -> None:
    """Sets the project's own turned-off states for one type.

    Args:
        db: Active session (not committed).
        project: The project.
        artefact_type: The registered record type.
        disabled: The states to turn off, or `None` to follow the nearest ancestor project (else every state on).
        actor_id: The acting user.

    Raises:
        HTTPException: 404 unknown type, 422 a state that is not optional, 409 a state the organisation requires.
    """
    _, definition = _validated_type(artefact_type)
    row = db.scalar(
        select(ProjectLifecycleSetting).where(
            ProjectLifecycleSetting.project_id == project.id, ProjectLifecycleSetting.artefact_type == artefact_type
        )
    )
    if disabled is None:
        if row is not None:
            db.delete(row)
        states: list[str] | None = None
    else:
        states = _validated_states(definition, disabled)
        blocked = sorted(set(states) & resolve_project_lifecycles(db, project)[artefact_type].enforced)
        if blocked:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"The organisation requires these states for a {definition.label}: {', '.join(blocked)}.",
            )
        if row is None:
            db.add(ProjectLifecycleSetting(project_id=project.id, artefact_type=artefact_type, disabled_states=states))
        else:
            row.disabled_states = states
    log_event(
        db, entity_type=AUDIT_ENTITY_TYPE, entity_id=project.id, action="updated", actor_id=actor_id,
        organization_id=project.organization_id, project_id=project.id,
        detail={"artefact_type": artefact_type, "disabled_states": states, "inherits": states is None},
    )
    db.flush()


def set_org_required(
    db: Session, *, organization: Organization, artefact_type: str, required: Iterable[str], actor_id: uuid.UUID,
) -> None:
    """Sets the states the organisation requires for one type.

    Args:
        db: Active session (not committed).
        organization: The organisation.
        artefact_type: The registered record type.
        required: The states to require (an empty list removes the requirement).
        actor_id: The acting user.

    Raises:
        HTTPException: 404 unknown type, 422 a state that is not optional.
    """
    _, definition = _validated_type(artefact_type)
    states = _validated_states(definition, required)
    rows = {
        row.state: row for row in db.scalars(
            select(OrganizationLifecycleRequirement).where(
                OrganizationLifecycleRequirement.organization_id == organization.id,
                OrganizationLifecycleRequirement.artefact_type == artefact_type,
            )
        )
    }
    for state, row in rows.items():
        if state not in states:
            db.delete(row)
    for state in states:
        if state not in rows:
            db.add(OrganizationLifecycleRequirement(organization_id=organization.id, artefact_type=artefact_type, state=state))
    log_event(
        db, entity_type=AUDIT_ENTITY_TYPE, entity_id=organization.id, action="updated", actor_id=actor_id,
        organization_id=organization.id, detail={"artefact_type": artefact_type, "required_states": states},
    )
    db.flush()


def add_exemption(
    db: Session, *, organization: Organization, artefact_type: str, project: Project, include_children: bool,
    actor_id: uuid.UUID,
) -> None:
    """Exempts a project from the organisation's required states of one type (or updates the exemption).

    Raises:
        HTTPException: 404 unknown type, 422 a project of another organisation.
    """
    _validated_type(artefact_type)
    if project.organization_id != organization.id:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "The project belongs to another organisation.")
    row = db.scalar(
        select(OrganizationLifecycleExemption).where(
            OrganizationLifecycleExemption.organization_id == organization.id,
            OrganizationLifecycleExemption.artefact_type == artefact_type,
            OrganizationLifecycleExemption.project_id == project.id,
        )
    )
    if row is None:
        db.add(OrganizationLifecycleExemption(
            organization_id=organization.id, artefact_type=artefact_type, project_id=project.id,
            include_children=include_children,
        ))
    else:
        row.include_children = include_children
    log_event(
        db, entity_type=AUDIT_ENTITY_TYPE, entity_id=organization.id, action="exemption_added", actor_id=actor_id,
        organization_id=organization.id, project_id=project.id,
        detail={"artefact_type": artefact_type, "include_children": include_children},
    )
    db.flush()


def remove_exemption(
    db: Session, *, organization: Organization, artefact_type: str, project_id: uuid.UUID, actor_id: uuid.UUID,
) -> None:
    """Removes a project's exemption.

    Raises:
        HTTPException: 404 when the project has no such exemption.
    """
    row = db.scalar(
        select(OrganizationLifecycleExemption).where(
            OrganizationLifecycleExemption.organization_id == organization.id,
            OrganizationLifecycleExemption.artefact_type == artefact_type,
            OrganizationLifecycleExemption.project_id == project_id,
        )
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That project has no exemption.")
    db.delete(row)
    log_event(
        db, entity_type=AUDIT_ENTITY_TYPE, entity_id=organization.id, action="exemption_removed", actor_id=actor_id,
        organization_id=organization.id, project_id=project_id, detail={"artefact_type": artefact_type},
    )
    db.flush()


def set_project_skip(db: Session, *, project: Project, allowed: bool | None, actor_id: uuid.UUID) -> None:
    """Sets whether the project lets a record skip steps.

    Args:
        db: Active session (not committed).
        project: The project.
        allowed: The choice, or `None` to follow the nearest ancestor project (else off).
        actor_id: The acting user.

    Raises:
        HTTPException: 409 when turning it on while the organisation forbids skipping and the project is not exempt.
    """
    row = db.scalar(select(ProjectLifecycleSkipSetting).where(ProjectLifecycleSkipSetting.project_id == project.id))
    if allowed and resolve_skip_policy(db, project).enforced:
        raise HTTPException(status.HTTP_409_CONFLICT, "The organisation does not allow skipping steps.")
    if allowed is None:
        if row is not None:
            db.delete(row)
    elif row is None:
        db.add(ProjectLifecycleSkipSetting(project_id=project.id, allowed=allowed))
    else:
        row.allowed = allowed
    log_event(
        db, entity_type=AUDIT_ENTITY_TYPE, entity_id=project.id, action="skip_updated", actor_id=actor_id,
        organization_id=project.organization_id, project_id=project.id,
        detail={"skip_allowed": allowed, "inherits": allowed is None},
    )
    db.flush()


def set_org_skip_forbidden(db: Session, *, organization: Organization, forbidden: bool, actor_id: uuid.UUID) -> None:
    """Sets whether the organisation forbids skipping steps in every project that is not exempt."""
    row = db.scalar(
        select(OrganizationLifecycleSkipPolicy).where(OrganizationLifecycleSkipPolicy.organization_id == organization.id)
    )
    if row is None:
        db.add(OrganizationLifecycleSkipPolicy(organization_id=organization.id, forbidden=forbidden))
    else:
        row.forbidden = forbidden
    log_event(
        db, entity_type=AUDIT_ENTITY_TYPE, entity_id=organization.id, action="skip_forbidden_updated", actor_id=actor_id,
        organization_id=organization.id, detail={"forbidden": forbidden},
    )
    db.flush()


def add_skip_exemption(
    db: Session, *, organization: Organization, project: Project, include_children: bool, actor_id: uuid.UUID,
) -> None:
    """Exempts a project (optionally with its nested children) from the organisation's ban on skipping steps.

    Raises:
        HTTPException: 422 for a project of another organisation.
    """
    if project.organization_id != organization.id:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "The project belongs to another organisation.")
    row = db.scalar(
        select(OrganizationLifecycleSkipExemption).where(
            OrganizationLifecycleSkipExemption.organization_id == organization.id,
            OrganizationLifecycleSkipExemption.project_id == project.id,
        )
    )
    if row is None:
        db.add(OrganizationLifecycleSkipExemption(
            organization_id=organization.id, project_id=project.id, include_children=include_children,
        ))
    else:
        row.include_children = include_children
    log_event(
        db, entity_type=AUDIT_ENTITY_TYPE, entity_id=organization.id, action="skip_exemption_added", actor_id=actor_id,
        organization_id=organization.id, project_id=project.id, detail={"include_children": include_children},
    )
    db.flush()


def remove_skip_exemption(
    db: Session, *, organization: Organization, project_id: uuid.UUID, actor_id: uuid.UUID,
) -> None:
    """Removes a project's exemption from the ban on skipping steps.

    Raises:
        HTTPException: 404 when the project has no such exemption.
    """
    row = db.scalar(
        select(OrganizationLifecycleSkipExemption).where(
            OrganizationLifecycleSkipExemption.organization_id == organization.id,
            OrganizationLifecycleSkipExemption.project_id == project_id,
        )
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That project has no exemption.")
    db.delete(row)
    log_event(
        db, entity_type=AUDIT_ENTITY_TYPE, entity_id=organization.id, action="skip_exemption_removed", actor_id=actor_id,
        organization_id=organization.id, project_id=project_id, detail={},
    )
    db.flush()


def organization_skip(db: Session, organization: Organization) -> dict:
    """The organisation's rule on skipping steps.

    Returns:
        `{"forbidden": bool, "exemptions": [(project id, include_children)]}`, exemptions in creation order.
    """
    forbidden = bool(db.scalar(
        select(OrganizationLifecycleSkipPolicy.forbidden).where(
            OrganizationLifecycleSkipPolicy.organization_id == organization.id
        )
    ))
    exemptions = [
        (ex.project_id, ex.include_children)
        for ex in db.scalars(
            select(OrganizationLifecycleSkipExemption)
            .where(OrganizationLifecycleSkipExemption.organization_id == organization.id)
            .order_by(OrganizationLifecycleSkipExemption.created_at)
        )
    ]
    return {"forbidden": forbidden, "exemptions": exemptions}


def enabled_for_organization(db: Session, organization_id: uuid.UUID, artefact_type: str, module_key: str) -> bool:
    """Whether the type's module (and the sub-component serving the type) is enabled for the organisation."""
    if not is_module_enabled(db, organization_id, module_key):
        return False
    definition = artefact_type_module(artefact_type)
    sub = None if definition is None else subcomponent_serving(definition, artefact_type)
    return sub is None or is_org_module_subcomponent_enabled(db, organization_id, module_key, sub.key)


def organization_lifecycles(db: Session, organization: Organization) -> list[dict]:
    """The organisation-level view: each type with optional states whose module the organisation has enabled, with its
    required states and exemptions.

    Returns:
        One dict per type (type-name order): `artefact_type`, `definition`, `required` and `exemptions`
        (`[(project id, include_children)]`).
    """
    required: dict[str, set[str]] = {}
    for req in db.scalars(
        select(OrganizationLifecycleRequirement).where(OrganizationLifecycleRequirement.organization_id == organization.id)
    ):
        required.setdefault(req.artefact_type, set()).add(req.state)
    exemptions: dict[str, list[tuple[uuid.UUID, bool]]] = {}
    for ex in db.scalars(
        select(OrganizationLifecycleExemption).where(OrganizationLifecycleExemption.organization_id == organization.id)
        .order_by(OrganizationLifecycleExemption.created_at)
    ):
        exemptions.setdefault(ex.artefact_type, []).append((ex.project_id, ex.include_children))
    return [
        {
            "artefact_type": artefact_type, "module_key": module_key, "definition": definition,
            "required": [s for s in definition.optional if s in required.get(artefact_type, ())],
            "exemptions": exemptions.get(artefact_type, []),
        }
        for artefact_type, (module_key, definition) in sorted(get_lifecycles().items())
        if definition.optional and enabled_for_organization(db, organization.id, artefact_type, module_key)
    ]


# --- bundles and templates ---------------------------------------------------------------------


def export_project(db: Session, project: Project) -> list[dict]:
    """The project's own choices as bundle entries, `[{"artefact_type", "disabled_states"}]`, ordered by type."""
    rows = db.scalars(
        select(ProjectLifecycleSetting).where(ProjectLifecycleSetting.project_id == project.id)
        .order_by(ProjectLifecycleSetting.artefact_type)
    )
    return [{"artefact_type": r.artefact_type, "disabled_states": list(r.disabled_states or [])} for r in rows]


def export_project_skip(db: Session, project: Project) -> dict:
    """The project's own choice on skipping steps as a bundle entry, `{"allowed": bool | None}` (`None` follows the
    ancestor project)."""
    row = db.scalar(select(ProjectLifecycleSkipSetting).where(ProjectLifecycleSkipSetting.project_id == project.id))
    return {"allowed": None if row is None else row.allowed}


def import_project_skip(db: Session, project: Project, entry: dict | None) -> None:
    """Applies a bundle's skip choice to `project`, stored as written: an organisation's ban beats it when the policy
    is resolved, so an import never lets a project skip steps the organisation forbids. Not committed."""
    allowed = (entry or {}).get("allowed")
    if allowed is None:
        return
    row = db.scalar(select(ProjectLifecycleSkipSetting).where(ProjectLifecycleSkipSetting.project_id == project.id))
    if row is None:
        db.add(ProjectLifecycleSkipSetting(project_id=project.id, allowed=bool(allowed)))
    else:
        row.allowed = bool(allowed)
    db.flush()


def import_project(
    db: Session, project: Project, entries: list[dict] | None, actor_id: uuid.UUID | None, warn: Callable[[str], None],
) -> None:
    """Applies bundle `entries` to `project`. A type no longer registered and a state a type no longer lets a project
    turn off are reported through `warn` and skipped, so a bundle never fails as a whole over one.

    The choice is stored as written: an organisation's required state beats it when the path is resolved
    (`resolve_project_lifecycles`), so an import can never turn off a state the organisation requires. Not committed.
    """
    definitions = get_lifecycles()
    for entry in entries or []:
        artefact_type = str(entry.get("artefact_type", ""))
        found = definitions.get(artefact_type)
        if found is None:
            warn(f"The lifecycle settings for {artefact_type or 'an unnamed type'} were not imported: unknown record type.")
            continue
        wanted = {str(s) for s in entry.get("disabled_states") or []}
        valid = [s for s in found[1].optional if s in wanted]
        if len(valid) != len(wanted):
            warn(f"Some states of the {found[1].label} lifecycle were not imported: they cannot be turned off.")
        row = db.scalar(
            select(ProjectLifecycleSetting).where(
                ProjectLifecycleSetting.project_id == project.id, ProjectLifecycleSetting.artefact_type == artefact_type
            )
        )
        if row is None:
            db.add(ProjectLifecycleSetting(project_id=project.id, artefact_type=artefact_type, disabled_states=valid))
        else:
            row.disabled_states = valid
    db.flush()


def copy_project(db: Session, source: Project, target: Project, actor_id: uuid.UUID | None) -> None:
    """Copies `source`'s own choices to `target` (a project made from a template)."""
    import_project(db, target, export_project(db, source), actor_id, lambda _message: None)
    import_project_skip(db, target, export_project_skip(db, source))


def export_org(db: Session, organization: Organization, project_ref_by_id: Mapping[uuid.UUID, str]) -> dict:
    """The organisation's required states and exemptions as bundle sections.

    Args:
        db: Active session (read only).
        organization: The organisation.
        project_ref_by_id: The bundle's portable reference of each project, so an exemption names a project the
            import can find again.

    Returns:
        `{"lifecycle_requirements": [{"artefact_type", "states"}], "lifecycle_exemptions": [{"artefact_type",
        "project_ref", "include_children"}], "lifecycle_skip": {"forbidden", "exemptions": [{"project_ref",
        "include_children"}]}}`, ordered by type.
    """
    required: dict[str, list[str]] = {}
    for req in db.scalars(
        select(OrganizationLifecycleRequirement).where(OrganizationLifecycleRequirement.organization_id == organization.id)
        .order_by(OrganizationLifecycleRequirement.artefact_type, OrganizationLifecycleRequirement.state)
    ):
        required.setdefault(req.artefact_type, []).append(req.state)
    exemptions = [
        {"artefact_type": ex.artefact_type, "project_ref": project_ref_by_id[ex.project_id], "include_children": ex.include_children}
        for ex in db.scalars(
            select(OrganizationLifecycleExemption).where(OrganizationLifecycleExemption.organization_id == organization.id)
            .order_by(OrganizationLifecycleExemption.artefact_type, OrganizationLifecycleExemption.created_at)
        )
        if ex.project_id in project_ref_by_id
    ]
    skip = organization_skip(db, organization)
    return {
        "lifecycle_requirements": [{"artefact_type": t, "states": required[t]} for t in sorted(required)],
        "lifecycle_exemptions": exemptions,
        "lifecycle_skip": {
            "forbidden": skip["forbidden"],
            "exemptions": [
                {"project_ref": project_ref_by_id[pid], "include_children": include_children}
                for pid, include_children in skip["exemptions"] if pid in project_ref_by_id
            ],
        },
    }


def import_org(
    db: Session, organization: Organization, data: dict, project_id_by_ref: Mapping[str, uuid.UUID],
    actor_id: uuid.UUID, warn: Callable[[str], None], *, keep_existing: bool = False,
) -> None:
    """Applies a bundle's required states and exemptions to `organization`.

    Args:
        db: Active session (not committed).
        organization: The target organisation.
        data: The bundle's `org.json`.
        project_id_by_ref: The imported projects by bundle reference (an exemption of a project that was not imported
            is skipped).
        actor_id: The acting user.
        warn: Receives a message for each entry that could not be applied.
        keep_existing: A merge keeps the organisation's own requirement of a type and adds only the types it has not
            set.
    """
    own = {r.artefact_type for r in db.scalars(
        select(OrganizationLifecycleRequirement).where(OrganizationLifecycleRequirement.organization_id == organization.id)
    )}
    for entry in data.get("lifecycle_requirements") or []:
        artefact_type = str(entry.get("artefact_type", ""))
        if keep_existing and artefact_type in own:
            continue
        try:
            set_org_required(
                db, organization=organization, artefact_type=artefact_type, required=entry.get("states") or [],
                actor_id=actor_id,
            )
        except HTTPException as error:
            warn(f"The required lifecycle states for {artefact_type or 'an unnamed type'} were not imported: {error.detail}")
    for entry in data.get("lifecycle_exemptions") or []:
        project_id = project_id_by_ref.get(str(entry.get("project_ref", "")))
        project = None if project_id is None else db.get(Project, project_id)
        if project is None:
            continue
        try:
            add_exemption(
                db, organization=organization, artefact_type=str(entry.get("artefact_type", "")), project=project,
                include_children=bool(entry.get("include_children")), actor_id=actor_id,
            )
        except HTTPException as error:
            warn(f"A lifecycle exemption was not imported: {error.detail}")
    skip = data.get("lifecycle_skip") or {}
    own_skip = db.scalar(
        select(OrganizationLifecycleSkipPolicy.id).where(OrganizationLifecycleSkipPolicy.organization_id == organization.id)
    )
    if skip and not (keep_existing and own_skip is not None):
        set_org_skip_forbidden(db, organization=organization, forbidden=bool(skip.get("forbidden")), actor_id=actor_id)
        for entry in skip.get("exemptions") or []:
            project_id = project_id_by_ref.get(str(entry.get("project_ref", "")))
            project = None if project_id is None else db.get(Project, project_id)
            if project is None:
                continue
            try:
                add_skip_exemption(
                    db, organization=organization, project=project, include_children=bool(entry.get("include_children")),
                    actor_id=actor_id,
                )
            except HTTPException as error:
                warn(f"A skip exemption was not imported: {error.detail}")
