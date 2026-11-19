"""
Module: modules.architecture.state_machine_export

The state machine diagrams' share of the project bundle (`export.py` calls these functions): each diagram with its
states, transitions, notes, tags, places and comments, and the ids and codes the bundle's links and comments need.

Responsibilities:
- `export_state_machines`: the diagrams as bundle rows, and the rows exported (for the link section).
- `import_state_machines`: recreates the diagrams, numbered afresh, with their states and transitions, and returns the
  new ids by bundled code so links and comments find them.
- `reset_for_template`: returns the section to fresh drafts for a template project.

Design decisions:
- **Portable keys.** A diagram names the element it describes by code (or, for one another owner shares, the owner
  reference `export.py` already uses for a connection's end). A state names its parent and a transition names its two
  states by the state's **name**, which is unique within a diagram; a pin's box is a state name and its line the
  transition's position in the diagram's list; a note's leader names a state by name and a transition by position, the same
  keys. A bundled code (`SMD-001`, `STE-004`) is information only: an import
  numbers afresh, and the codes key the links within the bundle.
- **Status is restored as exported.** The checks gate guards the move to `active` through the API; a bundle is a backup,
  and an active diagram may already carry errors (an edit is never refused for introducing one), so the import writes
  the status it was given. No approval is skipped, since this module has none.
- **A diagram whose element is not available is dropped with a warning**, with its states, as a connection whose end is
  missing is.
- **Notes are the block diagram's.** A note and its leaders are written and read by `note_bundle`, shared with the block
  diagram's bundle; only a leader's target is resolved here. A leader whose state or transition is not in the bundle is
  dropped with a warning and its note kept. A bundle written before notes existed has no `notes` key and reads as none.
- A state and a diagram take their tags and places through one helper each way, so a type that cannot be placed (a state)
  carries an empty list rather than a different code path.

Dependencies: this module's models and rules, `services.bundle_comments`, `services.placements`, `services.tags`.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.project import Project
from app.modules.architecture import note_bundle
from app.modules.architecture.diagram_line_path import bundle_default_shape, bundle_line_shape, clean_waypoints
from app.modules.architecture.diagrams import leaders_of
from app.modules.architecture.enums import SYMBOL_LABEL_LENGTH, AttachPoint, LabelPosition, LeaderKind, RecordStatus, StateKind
from app.modules.architecture.models import (
    ArchitectureDiagramNote,
    ArchitectureNoteLeader,
    ArchitectureState,
    ArchitectureStateMachineDiagram,
    ArchitectureTransition,
)
from app.modules.architecture.schemas import MAX_NOTE_LEADERS
from app.modules.architecture.service import (
    STATE_ARTEFACT_TYPE,
    STATE_CODE_PREFIX,
    STATE_MACHINE_ARTEFACT_TYPE,
    STATE_MACHINE_CODE_PREFIX,
)
from app.services.bundle_comments import export_comments, import_comments, strip_comments
from app.services.bundle_common import BundleImportWarnings, UserResolver
from app.services.external_references import prime_record_references, record_references, restore_record_references
from app.services.placements import prime_record_placements, record_placements, restore_record_placements
from app.services.sequences import generate_unique_code
from app.services.tags import prime_record_tag_names, record_tag_names, restore_record_tags
from app.services.template_reset import fresh_drafts

_NO_COMMENTS: dict[str, list[dict[str, Any]]] = {"comments": [], "comment_pins": []}
_KINDS = {kind.value for kind in StateKind}
_POINTS = {point.value for point in AttachPoint}
_LABEL_POSITIONS = {position.value for position in LabelPosition}


def _imported_label(raw: dict[str, Any]) -> str:
    """The symbol label of an imported state: the bundle's text trimmed and cut to the limit, and empty for an ordinary
    state (a file from another source may carry anything)."""
    kind = raw.get("kind")
    label = raw.get("label")
    if kind not in _KINDS or kind == StateKind.STATE.value or not isinstance(label, str):
        return ""
    return label.strip()[:SYMBOL_LABEL_LENGTH]


def _imported_label_position(raw: dict[str, Any]) -> str:
    """The label position of an imported state: the bundle's value when it is a known position and the state is a marker, and
    `inside` otherwise (a file from before the position existed, or from another source, may carry anything)."""
    position = raw.get("label_position")
    if raw.get("kind") not in _KINDS or raw.get("kind") == StateKind.STATE.value or position not in _LABEL_POSITIONS:
        return LabelPosition.INSIDE.value
    return str(position)


def _stamp(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _instant(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _classification(db: Session, artefact_type: str, record_id: UUID) -> dict[str, Any]:
    """A record's tags and places for its bundle row (a type that cannot be placed has no places)."""
    return {
        "tags": record_tag_names(db, artefact_type, record_id), "placements": record_placements(db, artefact_type, record_id),
        "external_references": record_references(db, artefact_type, record_id),
    }


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
    restore_record_references(
        db, organization_id=project.organization_id, record_project_id=project.id, actor_id=actor_id,
        artefact_type=artefact_type, artefact_id=record_id, entries=entry.get("external_references"),
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
        prime_record_references(db, artefact_type, record_ids)
    comments = export_comments(db, STATE_MACHINE_ARTEFACT_TYPE, ids, anchor)
    notes = list(db.scalars(
        select(ArchitectureDiagramNote).where(ArchitectureDiagramNote.state_machine_diagram_id.in_(ids))
        .order_by(ArchitectureDiagramNote.sort_order, ArchitectureDiagramNote.id)
    ))
    leaders = leaders_of(db, (n.id for n in notes))
    by_machine_notes: dict[UUID, list[ArchitectureDiagramNote]] = defaultdict(list)
    for n in notes:
        if n.state_machine_diagram_id is not None:
            by_machine_notes[n.state_machine_diagram_id].append(n)

    def leader_json(leader: ArchitectureNoteLeader) -> dict[str, Any] | None:
        """A leader's line and its target by name (a state) or position (a transition), or as a point; `None` for a
        target that is not in this bundle."""
        row = note_bundle.leader_json(leader)
        if leader.kind == LeaderKind.STATE.value and leader.state_id in state_names:
            row["state_name"] = state_names[leader.state_id]
        elif leader.kind == LeaderKind.TRANSITION.value and leader.transition_id in positions:
            row["transition_position"] = positions[leader.transition_id]
        elif leader.kind == LeaderKind.POINT.value:
            row["x"], row["y"] = leader.x, leader.y
        else:
            return None
        return row

    rows = [
        {
            "unique_code": m.unique_code, "name": m.name, "description": m.description, "status": m.status,
            "line_hops": m.line_hops, "line_shape": m.line_shape, "element": element_ref(m.element_id),
            "states": [
                {
                    "unique_code": s.unique_code, "name": s.name, "description": s.description, "kind": s.kind,
                    "parent_name": state_names.get(s.parent_state_id) if s.parent_state_id else None,
                    "entry_action": s.entry_action, "exit_action": s.exit_action, "activity": s.activity, "label": s.label,
                    "label_position": s.label_position,
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
                    "points": clean_waypoints(t.points), "line_shape": t.line_shape,
                }
                for t in by_machine_transitions.get(m.id, [])
            ],
            "notes": [
                {
                    **note_bundle.note_json(n),
                    "leaders": [j for row in leaders.get(n.id, []) if (j := leader_json(row)) is not None],
                }
                for n in by_machine_notes.get(m.id, [])
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


def _import_notes(
    db: Session, machine_id: UUID, raw_notes: Any, states: dict[str, ArchitectureState], transition_ids: dict[str, str],
    code: str, warnings: BundleImportWarnings,
) -> None:
    """Recreates a state machine diagram's notes and leaders. A leader whose state or transition was not imported, or whose
    point is not a finite number, is dropped with a warning and its note kept; at most `MAX_NOTE_LEADERS` leaders are kept per
    note and at most 200 notes per diagram (the API's caps; a bundle is not trusted to respect them).

    Args:
        db: Active session; rows are added and flushed, never committed.
        machine_id: The imported diagram.
        raw_notes: The bundle's `notes` (absent in an older bundle).
        states: The imported states by name.
        transition_ids: The imported transitions' ids by position in the bundle.
        code: The diagram's bundled code, for warnings.
        warnings: Receives a note for everything dropped.
    """
    if not isinstance(raw_notes, list):
        return
    pending: list[tuple[ArchitectureDiagramNote, dict[str, Any]]] = []
    for order, raw in enumerate(n for n in raw_notes[:200] if isinstance(n, dict)):
        row = note_bundle.note_row(raw, order, state_machine_diagram_id=machine_id)
        db.add(row)
        pending.append((row, raw))
    if not pending:
        return
    db.flush()  # a leader row names its note
    for row, raw in pending:
        leaders = raw.get("leaders")
        wanted = [item for item in (leaders[:MAX_NOTE_LEADERS] if isinstance(leaders, list) else []) if isinstance(item, dict)]
        for order, leader in enumerate(wanted):
            leader_row = note_bundle.leader_row(row.id, order, leader)
            kind = leader.get("kind")
            restored = False
            if kind == LeaderKind.STATE.value:
                state = states.get(leader.get("state_name") or "")
                if state is not None:
                    leader_row.state_id, restored = state.id, True
            elif kind == LeaderKind.TRANSITION.value:
                transition = transition_ids.get(str(leader.get("transition_position")))
                if transition is not None:
                    leader_row.transition_id, restored = UUID(transition), True
            elif kind == LeaderKind.POINT.value:
                x, y = leader.get("x"), leader.get("y")
                if (
                    isinstance(x, int | float) and isinstance(y, int | float) and not isinstance(x, bool) and not isinstance(y, bool)
                    and math.isfinite(x) and math.isfinite(y)
                ):
                    leader_row.x, leader_row.y, restored = float(x), float(y), True
            if restored:
                db.add(leader_row)
            else:
                warnings.add(f"State machine diagram {code}: a note's leader could not be restored — left out.")


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
            line_hops=bool(entry.get("line_hops")), line_shape=bundle_default_shape(entry), status=entry.get("status", "draft"),
            version=1, creator_id=creator, is_archived=archived,
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
                activity=raw.get("activity", ""), label=_imported_label(raw), label_position=_imported_label_position(raw),
                x=float(raw.get("x", 0)), y=float(raw.get("y", 0)),
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
                points=clean_waypoints(raw.get("points")), line_shape=bundle_line_shape(raw),
            )
            db.add(transition)
            db.flush()
            transition_ids[str(order)] = str(transition.id)

        _import_notes(db, machine.id, entry.get("notes"), by_name, transition_ids, code, warnings)

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
