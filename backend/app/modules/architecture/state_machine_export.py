"""
Module: modules.architecture.state_machine_export

The state machine diagrams' share of the project bundle (`export.py` calls these functions): each diagram with its
states, transitions, tags, places and comments, and the ids and codes the bundle's links and comments need.

Responsibilities:
- `export_state_machines`: the diagrams as bundle rows, and the rows exported (for the link section).
- `import_state_machines`: recreates the diagrams, numbered afresh, with their states and transitions, and returns the
  new ids by bundled code so links and comments find them.
- `reset_for_template`: returns the section to fresh drafts for a template project.

Design decisions:
- **Portable keys.** A diagram names the element it describes by code (or, for one another owner shares, the owner
  reference `export.py` already uses for a connection's end). A state names its parent and a transition names its two
  states by the state's **name**, which is unique within a diagram; a pin's box is a state name and its line the
  transition's position in the diagram's list. A bundled code (`SMD-001`, `STE-004`) is information only: an import
  numbers afresh, and the codes key the links within the bundle.
- **Status is restored as exported.** The checks gate guards the move to `active` through the API; a bundle is a backup,
  and an active diagram may already carry errors (an edit is never refused for introducing one), so the import writes
  the status it was given. No approval is skipped, since this module has none.
- **A diagram whose element is not available is dropped with a warning**, with its states, as a connection whose end is
  missing is.
- A state and a diagram take their tags and places through one helper each way, so a type that cannot be placed (a state)
  carries an empty list rather than a different code path.

Dependencies: this module's models and rules, `services.bundle_comments`, `services.placements`, `services.tags`.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.project import Project
from app.modules.architecture.enums import AttachPoint, RecordStatus, StateKind
from app.modules.architecture.models import (
    ArchitectureState,
    ArchitectureStateMachineDiagram,
    ArchitectureTransition,
)
from app.modules.architecture.service import (
    STATE_ARTEFACT_TYPE,
    STATE_CODE_PREFIX,
    STATE_MACHINE_ARTEFACT_TYPE,
    STATE_MACHINE_CODE_PREFIX,
)
from app.services.bundle_comments import export_comments, import_comments, strip_comments
from app.services.bundle_common import BundleImportWarnings, UserResolver
from app.services.placements import prime_record_placements, record_placements, restore_record_placements
from app.services.sequences import generate_unique_code
from app.services.tags import prime_record_tag_names, record_tag_names, restore_record_tags
from app.services.template_reset import fresh_drafts

_NO_COMMENTS: dict[str, list[dict[str, Any]]] = {"comments": [], "comment_pins": []}
_KINDS = {kind.value for kind in StateKind}
_POINTS = {point.value for point in AttachPoint}


def _stamp(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _instant(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _classification(db: Session, artefact_type: str, record_id: UUID) -> dict[str, Any]:
    """A record's tags and places for its bundle row (a type that cannot be placed has no places)."""
    return {"tags": record_tag_names(db, artefact_type, record_id), "placements": record_placements(db, artefact_type, record_id)}


def _restore_classification(
    db: Session, project: Project, actor_id: UUID, artefact_type: str, record_id: UUID, entry: dict[str, Any],
) -> None:
    """Applies a bundle row's tags and places to its new record."""
    restore_record_tags(
        db, organization_id=project.organization_id, record_project_id=project.id, actor_id=actor_id,
        artefact_type=artefact_type, artefact_id=record_id, names=entry.get("tags"),
    )
    restore_record_placements(
        db, project_id=project.id, actor_id=actor_id, artefact_type=artefact_type, artefact_id=record_id,
        entries=entry.get("placements"),
    )


def load_machines(db: Session, project: Project) -> list[ArchitectureStateMachineDiagram]:
    """The project's state machine diagrams (archived included: a bundle is a backup), by code."""
    return list(db.scalars(
        select(ArchitectureStateMachineDiagram).where(ArchitectureStateMachineDiagram.project_id == project.id)
        .order_by(ArchitectureStateMachineDiagram.unique_code)
    ))


def export_state_machines(
    db: Session, machines: Sequence[ArchitectureStateMachineDiagram], element_ref: Callable[[UUID], dict[str, Any]],
    email_of: Callable[[UUID | None], str | None],
) -> tuple[list[dict[str, Any]], list[ArchitectureState]]:
    """The diagrams as bundle rows, with their states and transitions, and the states exported.

    Args:
        db: Active session (read only).
        machines: The diagrams (`load_machines`).
        element_ref: How the bundle names the element a diagram describes (`export._element_ref`).
        email_of: The email a user id is exported as.

    Returns:
        `(rows, states)`.
    """
    if not machines:
        return [], []
    ids = [m.id for m in machines]
    states = list(db.scalars(
        select(ArchitectureState).where(ArchitectureState.state_machine_diagram_id.in_(ids)).order_by(ArchitectureState.unique_code)
    ))
    transitions = list(db.scalars(
        select(ArchitectureTransition).where(ArchitectureTransition.state_machine_diagram_id.in_(ids))
        .order_by(ArchitectureTransition.sort_order, ArchitectureTransition.id)
    ))
    by_machine_states: dict[UUID, list[ArchitectureState]] = defaultdict(list)
    for s in states:
        by_machine_states[s.state_machine_diagram_id].append(s)
    by_machine_transitions: dict[UUID, list[ArchitectureTransition]] = defaultdict(list)
    for t in transitions:
        by_machine_transitions[t.state_machine_diagram_id].append(t)
    state_names = {s.id: s.name for s in states}
    positions = {t.id: str(i) for ts in by_machine_transitions.values() for i, t in enumerate(ts)}

    def anchor(kind: str, key: str) -> str | None:
        try:
            target = UUID(key)
        except ValueError:
            return None
        return (state_names if kind == "node" else positions).get(target)

    for artefact_type, record_ids in ((STATE_MACHINE_ARTEFACT_TYPE, ids), (STATE_ARTEFACT_TYPE, [s.id for s in states])):
        prime_record_tag_names(db, artefact_type, record_ids)
        prime_record_placements(db, artefact_type, record_ids)
    comments = export_comments(db, STATE_MACHINE_ARTEFACT_TYPE, ids, anchor)
    rows = [
        {
            "unique_code": m.unique_code, "name": m.name, "description": m.description, "status": m.status,
            "element": element_ref(m.element_id),
            "states": [
                {
                    "unique_code": s.unique_code, "name": s.name, "description": s.description, "kind": s.kind,
                    "parent_name": state_names.get(s.parent_state_id) if s.parent_state_id else None,
                    "entry_action": s.entry_action, "exit_action": s.exit_action, "activity": s.activity,
                    "x": s.x, "y": s.y, "width": s.width, "height": s.height, "collapsed": s.collapsed,
                    **_classification(db, STATE_ARTEFACT_TYPE, s.id),
                }
                for s in by_machine_states.get(m.id, [])
            ],
            "transitions": [
                {
                    "source": state_names.get(t.source_state_id), "target": state_names.get(t.target_state_id),
                    "event": t.event, "guard": t.guard, "action": t.action, "description": t.description,
                    "source_point": t.source_point, "target_point": t.target_point,
                }
                for t in by_machine_transitions.get(m.id, [])
            ],
            "created_by_email": email_of(m.creator_id), "created_at": _stamp(m.created_at),
            "is_archived": m.is_archived, "archived_at": _stamp(m.archived_at), "archived_by_email": email_of(m.archived_by),
            **_classification(db, STATE_MACHINE_ARTEFACT_TYPE, m.id),
            **comments.get(m.id, _NO_COMMENTS),
        }
        for m in machines
    ]
    return rows, states


def reset_for_template(entries: list[dict[str, Any]], kept_elements: set[str]) -> list[dict[str, Any]]:
    """A template's state machine diagrams: fresh drafts without creators, archived ones or comments, and only those
    describing an element the template itself carries (a template points at nothing outside itself).

    Args:
        entries: The section's rows (changed in place).
        kept_elements: The codes of the elements the template keeps.

    Returns:
        The rows that remain.
    """
    fresh_drafts(entries, status=RecordStatus.DRAFT.value)
    strip_comments(entries)
    return [e for e in entries if (e.get("element") or {}).get("code") in kept_elements]


def import_state_machines(
    db: Session, project: Project, entries: list[dict[str, Any]], element_for: Callable[[dict[str, Any] | None], UUID | None],
    creator_fallback: UUID, users: UserResolver, warnings: BundleImportWarnings,
) -> tuple[dict[str, UUID], dict[str, UUID]]:
    """Recreates the bundle's state machine diagrams, numbered afresh, with their states, transitions, tags, places and
    comments. A diagram whose element is not available is skipped with a warning; a state or transition that cannot be
    placed in its diagram is dropped with one.

    Args:
        db: Active session; rows are added and flushed, never committed.
        project: The importing project.
        entries: The section's rows.
        element_for: Resolves a row's `element` reference to an element id the person may read, or `None`.
        creator_fallback: The user recorded as creator when a row's creator cannot be resolved.
        users: Resolves the `*_email` references.
        warnings: Receives a note for everything dropped.

    Returns:
        `(diagram ids by bundled code, state ids by bundled code)`, for the links and comments.
    """
    machines: dict[str, UUID] = {}
    state_codes: dict[str, UUID] = {}
    for entry in entries:
        code = entry.get("unique_code", "")
        element_id = element_for(entry.get("element"))
        if element_id is None:
            warnings.add(f"State machine diagram {code or '?'} skipped — the element it describes is not available here.")
            continue
        creator = users.resolve(entry.get("created_by_email"), required=True, context=f"State machine diagram {code} creator") or creator_fallback
        archived = bool(entry.get("is_archived"))
        machine = ArchitectureStateMachineDiagram(
            project_id=project.id,
            unique_code=generate_unique_code(db, project, STATE_MACHINE_ARTEFACT_TYPE, STATE_MACHINE_CODE_PREFIX),
            name=entry["name"], description=entry.get("description", ""), element_id=element_id,
            status=entry.get("status", "draft"), version=1, creator_id=creator, is_archived=archived,
            archived_at=_instant(entry.get("archived_at")),
            archived_by=(users.resolve(entry.get("archived_by_email"), required=False, context=f"State machine diagram {code} archiver") or creator)
            if archived else None,
        )
        created_at = _instant(entry.get("created_at"))
        if created_at is not None:
            machine.created_at = created_at
        db.add(machine)
        db.flush()
        machines[code] = machine.id
        _restore_classification(db, project, creator, STATE_MACHINE_ARTEFACT_TYPE, machine.id, entry)

        by_name: dict[str, ArchitectureState] = {}
        for raw in entry.get("states", []):
            name = raw.get("name", "")
            if not name or name.lower() in {n.lower() for n in by_name}:
                warnings.add(f"State machine diagram {code}: a state without a usable name was left out.")
                continue
            state = ArchitectureState(
                state_machine_diagram_id=machine.id, project_id=project.id,
                unique_code=generate_unique_code(db, project, STATE_ARTEFACT_TYPE, STATE_CODE_PREFIX),
                name=name, description=raw.get("description", ""), kind=raw.get("kind") if raw.get("kind") in _KINDS else "state",
                parent_state_id=None, entry_action=raw.get("entry_action", ""), exit_action=raw.get("exit_action", ""),
                activity=raw.get("activity", ""), x=float(raw.get("x", 0)), y=float(raw.get("y", 0)),
                width=float(raw.get("width", 160)), height=float(raw.get("height", 64)), collapsed=bool(raw.get("collapsed")),
                creator_id=creator,
            )
            db.add(state)
            db.flush()
            by_name[name] = state
            state_codes[raw.get("unique_code", "")] = state.id
            _restore_classification(db, project, creator, STATE_ARTEFACT_TYPE, state.id, raw)
        for raw in entry.get("states", []):
            parent_name = raw.get("parent_name")
            child = by_name.get(raw.get("name", ""))
            if not parent_name or child is None:
                continue
            parent = by_name.get(parent_name)
            if parent is None or parent.kind != StateKind.STATE.value or parent is child:
                warnings.add(f"State machine diagram {code}: the parent of a state is not available — left at the top level.")
                continue
            child.parent_state_id = parent.id
        db.flush()

        transition_ids: dict[str, str] = {}
        for order, raw in enumerate(entry.get("transitions", [])):
            source, target = by_name.get(raw.get("source") or ""), by_name.get(raw.get("target") or "")
            if source is None or target is None:
                warnings.add(f"State machine diagram {code}: a transition between states not in the bundle was left out.")
                continue
            transition = ArchitectureTransition(
                state_machine_diagram_id=machine.id, source_state_id=source.id, target_state_id=target.id,
                event=raw.get("event", ""), guard=raw.get("guard", ""), action=raw.get("action", ""),
                description=raw.get("description", ""), sort_order=len(transition_ids),
                source_point=raw.get("source_point") if raw.get("source_point") in _POINTS else None,
                target_point=raw.get("target_point") if raw.get("target_point") in _POINTS else None,
            )
            db.add(transition)
            db.flush()
            transition_ids[str(order)] = str(transition.id)

        def resolve(kind: str, key: str, names=by_name, transitions=transition_ids) -> str | None:
            if kind == "node":
                found = names.get(key)
                return str(found.id) if found else None
            return transitions.get(key)

        import_comments(
            db, project=project, artefact_type=STATE_MACHINE_ARTEFACT_TYPE, record_id=machine.id, entry=entry, users=users,
            warnings=warnings, context=f"State machine diagram {code}", resolve_anchor=resolve,
        )
    return machines, state_codes
