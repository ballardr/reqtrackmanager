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

Design decisions:
- A state is turned off for a project, never deleted: a record already in it stays valid and can move on, and turning
  the state back on restores the path. A move into a turned-off state is refused; the move is offered to its
  successors instead.
- A state a type marks gated or off-path is never optional, so a turned-off state can never remove an approval.
- An organisation requirement beats a project's choice; an exemption (per type, per project, optionally with nested
  children) lifts the requirement for that project only. The project's stored choice is kept, so a requirement later
  removed gives the project's own choice back.
- Resolution reads four small tables per call and never loops per record; list responses read it once per request.

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
    ProjectLifecycleSetting,
)
from app.models.organization import Organization
from app.models.project import Project
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
        unknown, a gated or path state missing from the table, a move to an unknown state.
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
) -> tuple[str, ...]:
    """Enforces a state move in `project_id`.

    Args:
        db: Active session (read only).
        project_id: The record's project, or `None` for a record the organisation owns, which has no project to
            configure and keeps the type's full path.
        artefact_type: The registered record type.
        current: The record's current state.
        target: The state it is moved to.

    Returns:
        The turned-off states the move passes over, in order (empty for a move to the next state), so the caller can
        still apply the checks of those states.

    Raises:
        ValueError: When the move is not legal here; the message names the states that are.
        KeyError: When the type has no registered lifecycle (a programming error).
    """
    if project_id is None:
        definition = get_lifecycles()[artefact_type][1]
        disabled: frozenset[str] = frozenset()
    else:
        resolved = lifecycle_for(db, project_id, artefact_type)
        definition, disabled = resolved.definition, resolved.disabled
    moves = effective_moves(definition, disabled, current)
    if target in moves:
        return moves[target]
    label = definition.label

    def name(state: str) -> str:
        return definition.labels.get(state, state)

    head = f"Cannot move {_article(label)} {label} from '{name(current)}' to '{name(target)}'."
    if target in disabled and target in {n for ns in definition.transitions.values() for n in ns}:
        head += f" The state '{name(target)}' is turned off in this project."
    if moves:
        head += " Allowed next states: " + ", ".join(f"'{name(s)}'" for s in moves) + "."
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


def _enabled_for_organization(db: Session, organization_id: uuid.UUID, artefact_type: str, module_key: str) -> bool:
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
        if definition.optional and _enabled_for_organization(db, organization.id, artefact_type, module_key)
    ]


# --- bundles and templates ---------------------------------------------------------------------


def export_project(db: Session, project: Project) -> list[dict]:
    """The project's own choices as bundle entries, `[{"artefact_type", "disabled_states"}]`, ordered by type."""
    rows = db.scalars(
        select(ProjectLifecycleSetting).where(ProjectLifecycleSetting.project_id == project.id)
        .order_by(ProjectLifecycleSetting.artefact_type)
    )
    return [{"artefact_type": r.artefact_type, "disabled_states": list(r.disabled_states or [])} for r in rows]


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


def export_org(db: Session, organization: Organization, project_ref_by_id: Mapping[uuid.UUID, str]) -> dict:
    """The organisation's required states and exemptions as bundle sections.

    Args:
        db: Active session (read only).
        organization: The organisation.
        project_ref_by_id: The bundle's portable reference of each project, so an exemption names a project the
            import can find again.

    Returns:
        `{"lifecycle_requirements": [{"artefact_type", "states"}], "lifecycle_exemptions": [{"artefact_type",
        "project_ref", "include_children"}]}`, ordered by type.
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
    return {
        "lifecycle_requirements": [{"artefact_type": t, "states": required[t]} for t in sorted(required)],
        "lifecycle_exemptions": exemptions,
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
