"""
Module: modules.architecture.diagrams

The rules for diagrams and what they hold: create, edit, move between statuses, archive and delete a diagram;
replace its layout (placements, notes, line anchors and boundary boxes) or toggles; place or unplace one
element. The read side (the resolved view) is in `diagram_view`.

Responsibilities:
- Validate every reference a diagram stores: a scope or placed element the viewer may read, a toggle member,
  a rule's types.
- Advance the diagram's `version` on every change to the diagram or anything it holds, and write one audit
  event per change holding ids, counts and field names, never names or text.
- Read lists in bulk (`diagram_outs`): one statement per kind of related row however many diagrams are listed.

Design decisions:
- A diagram is a view: deleting a diagram or a placement loses nothing from the model; deleting an element
  removes its placements (a database cascade). The model's own rules (an element another project uses cannot
  be deleted) apply.
- One lock for the whole diagram: a save quotes the `version` it was based on and the row is locked while it
  is checked. Moving a box and adding a toggle advance the same counter, so a stale editor is told before it
  overwrites.
- Who may be placed: an element the viewer can read (the project's own, or shared by another owner). A
  retired shared element cannot be newly placed, but an existing placement is kept when the diagram is saved
  again, so a revoked or retired element never makes a diagram unsaveable. An archived element cannot be
  newly placed.
- A layout save replaces: the editor owns undo and redo, so it saves the complete placement and note lists
  and an element left out is unplaced. An id naming a note or toggle of another diagram is refused.
- One note mechanism for both diagram types: a state machine diagram's notes are rows of the same tables as a
  block diagram's (`sync_notes`, `machine_notes_of`); only what a leader may point at differs, so the owner
  passes that check.
- Line anchors follow the boxes: an anchor joins two placed elements, so unplacing either removes it (the
  layout save and `remove_placement`), and a save may not name an unplaced element. An anchor whose line is
  not currently drawn (a view switch hides an end, or roll-up draws another pair) is kept and unused.
- A route belongs to a pair of boxes or to one connection: a pair's route moves every connection on the line;
  a connection's own route (`connection_id`, one per connection, which must be the project's) draws it apart.
  Deleting the connection removes its route (a database cascade); a route whose boxes the connection no longer
  joins is kept and unused.
- Boundary boxes follow the scope: a box stands for an outer connection of the diagram's scope
  (`boundaries`), is saved with the layout and is removed when the scope changes; a stored box whose
  connection stops being outer is kept and not drawn.
- Toggle rules name vocabulary rows (types and domains) and tag names, never records; a toggle's manual
  members are the only record references and each must be readable.

Dependencies: `records` (the shared rule errors, version lock and audit helpers), `visibility`, `service`,
core `services.sequences`, `services.tags`, `services.placements`, `services.audit`.
"""

from __future__ import annotations

import enum
import math
import uuid
from collections.abc import Callable, Iterable, Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.user import User
from app.modules.architecture import boundaries as boundary_rules
from app.modules.architecture.enums import AttachPoint, LeaderKind, LineEnd, LineShape, NoteAlign, NoteSizeMode, NoteTone, RecordStatus
from app.modules.architecture.labels import INACTIVE_STATUSES
from app.modules.architecture.lifecycles import ProjectMoves
from app.modules.architecture.models import (
    ArchitectureConnection,
    ArchitectureDiagram,
    ArchitectureDiagramAnchor,
    ArchitectureDiagramNote,
    ArchitectureDiagramPlacement,
    ArchitectureDiagramToggle,
    ArchitectureDiagramToggleMember,
    ArchitectureElement,
    ArchitectureNoteLeader,
)
from app.modules.architecture.records import (
    ElementOwner,
    RuleError,
    _check_version,
    _detail,
    _forget,
    _touch,
    _usable_folder,
    folder_paths,
    require_lifecycle_move,
)
from app.modules.architecture.schemas import (
    AnchorIn,
    BoundaryIn,
    DiagramCreate,
    DiagramOut,
    DiagramUpdate,
    LayoutSave,
    LeaderIn,
    LeaderOut,
    NoteIn,
    NoteOut,
    PlacementIn,
    ToggleIn,
    TogglesSave,
    WaypointIn,
)
from app.modules.architecture.service import (
    CONNECTION_TYPES,
    DIAGRAM_ARTEFACT_TYPE,
    DIAGRAM_CODE_PREFIX,
    DOMAINS,
    ELEMENT_TYPES,
)
from app.modules.architecture.transitions import move_refusal
from app.modules.architecture.visibility import Viewer, visible_element_ids
from app.services.audit import log_event
from app.services.sequences import generate_unique_code

#: The grid `populate` lays the scope's children out on: columns, cell size and gap.
_GRID_COLUMNS = 4
_CELL_WIDTH, _CELL_HEIGHT, _GAP = 160.0, 80.0, 40.0

#: The most elements `populate` places in one request (a larger scope is placed in several saves).
MAX_POPULATE = 200


# --- Lookups ---------------------------------------------------------------


def get_diagram(db: Session, project_id: uuid.UUID, diagram_id: uuid.UUID, *, lock: bool = False) -> ArchitectureDiagram:
    """The diagram in the project; `lock` takes a row lock for a write.

    Raises:
        RuleError: 404 if it does not exist in the project.
    """
    query = select(ArchitectureDiagram).where(
        ArchitectureDiagram.id == diagram_id, ArchitectureDiagram.project_id == project_id,
    )
    diagram = db.scalar(query.with_for_update() if lock else query)
    if diagram is None:
        raise RuleError("Diagram not found.", 404)
    return diagram


def list_diagrams(db: Session, project_id: uuid.UUID, *, include_archived: bool = False) -> list[ArchitectureDiagram]:
    """The project's diagrams ordered by code."""
    query = select(ArchitectureDiagram).where(ArchitectureDiagram.project_id == project_id)
    if not include_archived:
        query = query.where(ArchitectureDiagram.is_archived.is_(False))
    return list(db.scalars(query.order_by(ArchitectureDiagram.unique_code)))


def _audit(db: Session, diagram_id: uuid.UUID, action: str, actor: User, project_id: uuid.UUID, **detail: Any) -> None:
    """Writes the audit event for a change to a diagram: ids, counts and field names only."""
    log_event(
        db, entity_type=DIAGRAM_ARTEFACT_TYPE, entity_id=diagram_id, action=action, actor_id=actor.id,
        project_id=project_id, detail=_detail(detail),
    )


# --- Checks ----------------------------------------------------------------


def _check_new_element(db: Session, viewer: Viewer, element_ids: Iterable[uuid.UUID]) -> None:
    """Checks that every element can be newly placed (or used as a scope): readable by the viewer, not archived, and
    not a retired element of another owner.

    Raises:
        RuleError: 400 otherwise (an element the viewer cannot see looks the same as one that does not exist).
    """
    wanted = set(element_ids)
    if not wanted:
        return
    readable = visible_element_ids(db, viewer, wanted)
    rows = {e.id: e for e in db.scalars(select(ArchitectureElement).where(ArchitectureElement.id.in_(readable)))} if readable else {}
    for element_id in wanted:
        element = rows.get(element_id)
        if element is None or element.is_archived:
            raise RuleError("An element is not available for this project.", 400)
        if element.project_id != viewer.project_id and element.status in INACTIVE_STATUSES:
            raise RuleError("A retired element of another owner cannot be newly added.", 400)


def _check_box(placement: PlacementIn | NoteIn | BoundaryIn) -> None:
    """Rejects a box that is not finite (the schema bounds each number; this guards a value that slips through)."""
    if not all(math.isfinite(v) for v in (placement.x, placement.y, placement.width, placement.height)):
        raise RuleError("A diagram box must have finite coordinates.", 400)


# --- Diagrams --------------------------------------------------------------


def create_diagram(db: Session, project: Any, actor: User, payload: DiagramCreate) -> ArchitectureDiagram:
    """Creates a diagram (and, with `populate`, places the scope's children). The caller commits.

    Raises:
        RuleError: 400 for a scope element the person cannot use.
    """
    viewer = Viewer.of_user(actor, project)
    if payload.scope_element_id is not None:
        _check_new_element(db, viewer, [payload.scope_element_id])
    if payload.folder_id is not None:
        _usable_folder(db, ElementOwner.of_project(project), "diagram", payload.folder_id)
    diagram = ArchitectureDiagram(
        project_id=project.id,
        unique_code=generate_unique_code(db, project, DIAGRAM_ARTEFACT_TYPE, DIAGRAM_CODE_PREFIX),
        name=payload.name.strip(), purpose=payload.purpose, scope_element_id=payload.scope_element_id,
        connection_detail=payload.connection_detail, line_hops=payload.line_hops, show_connection_names=payload.show_connection_names,
        line_shape=payload.line_shape.value,
        folder_id=payload.folder_id,
        status=(RecordStatus.ACTIVE if payload.activate else RecordStatus.DRAFT).value, version=1, creator_id=actor.id,
        is_archived=False,
    )
    db.add(diagram)
    db.flush()
    placed = _populate(db, diagram, project.id) if payload.populate else 0
    _audit(db, diagram.id, "created", actor, project.id, unique_code=diagram.unique_code, status=diagram.status, placed=placed)
    return diagram


def _populate(db: Session, diagram: ArchitectureDiagram, project_id: uuid.UUID) -> int:
    """Places the project's own children of the scope element (the root elements for the system context) on a grid,
    up to `MAX_POPULATE`. Returns how many were placed."""
    query = select(ArchitectureElement.id).where(
        ArchitectureElement.project_id == project_id, ArchitectureElement.is_archived.is_(False),
        ArchitectureElement.parent_id == diagram.scope_element_id if diagram.scope_element_id is not None
        else ArchitectureElement.parent_id.is_(None),
    ).order_by(ArchitectureElement.unique_code).limit(MAX_POPULATE)
    ids = list(db.scalars(query))
    for index, element_id in enumerate(ids):
        column, row = index % _GRID_COLUMNS, index // _GRID_COLUMNS
        db.add(ArchitectureDiagramPlacement(
            diagram_id=diagram.id, element_id=element_id, x=column * (_CELL_WIDTH + _GAP), y=row * (_CELL_HEIGHT + _GAP),
            width=_CELL_WIDTH, height=_CELL_HEIGHT, collapsed=False,
        ))
    db.flush()
    return len(ids)


def update_diagram(
    db: Session, project: Any, actor: User, diagram_id: uuid.UUID, payload: DiagramUpdate,
) -> ArchitectureDiagram:
    """Applies the fields the body names to a diagram. The caller commits.

    Raises:
        RuleError: 404 if absent, 409 on a stale `version`, 400 for a scope element the person cannot use.
    """
    diagram = get_diagram(db, project.id, diagram_id, lock=True)
    _check_version(diagram, payload.version)
    given = payload.model_fields_set
    changes: dict[str, Any] = {}
    if payload.name is not None and payload.name.strip() != diagram.name:
        changes["name"] = payload.name.strip()
    if payload.purpose is not None and payload.purpose != diagram.purpose:
        changes["purpose"] = payload.purpose
    if payload.connection_detail is not None and payload.connection_detail != diagram.connection_detail:
        changes["connection_detail"] = payload.connection_detail
    if payload.line_hops is not None and payload.line_hops != diagram.line_hops:
        changes["line_hops"] = payload.line_hops
    if payload.show_connection_names is not None and payload.show_connection_names != diagram.show_connection_names:
        changes["show_connection_names"] = payload.show_connection_names
    if payload.line_shape is not None and payload.line_shape.value != diagram.line_shape:
        changes["line_shape"] = payload.line_shape.value
    if "scope_element_id" in given and payload.scope_element_id != diagram.scope_element_id:
        if payload.scope_element_id is not None:
            _check_new_element(db, Viewer.of_user(actor, project), [payload.scope_element_id])
        changes["scope_element_id"] = payload.scope_element_id
    if "folder_id" in given and payload.folder_id != diagram.folder_id:
        if payload.folder_id is not None:
            _usable_folder(db, ElementOwner.of_project(project), "diagram", payload.folder_id)
        changes["folder_id"] = payload.folder_id
    if not changes:
        return diagram
    _touch(diagram, **changes)
    db.flush()
    cleared = boundary_rules.clear_boundaries(db, diagram.id) if "scope_element_id" in changes else 0
    _audit(
        db, diagram.id, "updated", actor, project.id, fields=sorted(changes),
        **({"boundaries_removed": cleared} if cleared else {}),
    )
    return diagram


def change_diagram_status(
    db: Session, project_id: uuid.UUID, actor: User, diagram_id: uuid.UUID, version: int, status: RecordStatus,
) -> ArchitectureDiagram:
    """Moves a diagram to `status`. The caller commits.

    Raises:
        RuleError: 404 if absent, 409 on a stale version or when the status is unchanged.
    """
    diagram = get_diagram(db, project_id, diagram_id, lock=True)
    _check_version(diagram, version)
    refusal = move_refusal(diagram.status, status)
    if refusal:
        raise RuleError(refusal, 409)
    require_lifecycle_move(db, project_id, DIAGRAM_ARTEFACT_TYPE, diagram.id, diagram.status, status)
    previous = diagram.status
    _touch(diagram, status=status.value)
    db.flush()
    _audit(db, diagram.id, "status_changed", actor, project_id, previous=previous, status=status.value)
    return diagram


def set_diagram_archived(
    db: Session, project_id: uuid.UUID, actor: User, diagram_id: uuid.UUID, archived: bool,
) -> ArchitectureDiagram:
    """Archives or unarchives a diagram. The caller commits.

    Raises:
        RuleError: 404 if absent.
    """
    diagram = get_diagram(db, project_id, diagram_id, lock=True)
    if diagram.is_archived == archived:
        return diagram
    diagram.is_archived = archived
    diagram.archived_at = datetime.now(UTC) if archived else None
    diagram.archived_by = actor.id if archived else None
    diagram.version += 1
    db.flush()
    _audit(db, diagram.id, "archived" if archived else "unarchived", actor, project_id)
    return diagram


def delete_diagram(db: Session, project_id: uuid.UUID, actor: User, diagram_id: uuid.UUID) -> None:
    """Deletes a diagram with its placements, notes and toggles (a database cascade), and the links, tags and places
    that refer to it. The model's elements and connections are untouched. The caller commits.

    Raises:
        RuleError: 404 if absent.
    """
    diagram = get_diagram(db, project_id, diagram_id, lock=True)
    _forget(db, DIAGRAM_ARTEFACT_TYPE, diagram.id)
    db.delete(diagram)
    db.flush()
    _audit(db, diagram.id, "deleted", actor, project_id)


# --- Layout ----------------------------------------------------------------


def placements_of(db: Session, diagram_id: uuid.UUID) -> list[ArchitectureDiagramPlacement]:
    """The diagram's placements in the order they were made."""
    return list(db.scalars(
        select(ArchitectureDiagramPlacement).where(ArchitectureDiagramPlacement.diagram_id == diagram_id)
        .order_by(ArchitectureDiagramPlacement.created_at, ArchitectureDiagramPlacement.id)
    ))


def notes_of(db: Session, diagram_id: uuid.UUID) -> list[ArchitectureDiagramNote]:
    """The block diagram's notes in order."""
    return list(db.scalars(
        select(ArchitectureDiagramNote).where(ArchitectureDiagramNote.diagram_id == diagram_id)
        .order_by(ArchitectureDiagramNote.sort_order, ArchitectureDiagramNote.id)
    ))


def machine_notes_of(db: Session, state_machine_diagram_id: uuid.UUID) -> list[ArchitectureDiagramNote]:
    """The state machine diagram's notes in order."""
    return list(db.scalars(
        select(ArchitectureDiagramNote).where(ArchitectureDiagramNote.state_machine_diagram_id == state_machine_diagram_id)
        .order_by(ArchitectureDiagramNote.sort_order, ArchitectureDiagramNote.id)
    ))


def anchors_of(db: Session, diagram_id: uuid.UUID) -> list[ArchitectureDiagramAnchor]:
    """The diagram's line anchors in a stable order."""
    return list(db.scalars(
        select(ArchitectureDiagramAnchor).where(ArchitectureDiagramAnchor.diagram_id == diagram_id)
        .order_by(ArchitectureDiagramAnchor.created_at, ArchitectureDiagramAnchor.id)
    ))


def _check_anchors(db: Session, project_id: uuid.UUID, anchors: Sequence[AnchorIn], placed: set[uuid.UUID]) -> None:
    """Checks the anchors of a save: both ends placed and different, one pair route per pair (either direction) and one
    route per connection, a point, vertex or shape given for a pair's route, and a connection that is this project's.

    Raises:
        RuleError: 400 otherwise.
    """
    seen: set[frozenset[uuid.UUID]] = set()
    seen_connections: set[uuid.UUID] = set()
    for anchor in anchors:
        if anchor.source_element_id == anchor.target_element_id:
            raise RuleError("A line joins two different elements.", 400)
        if (
            anchor.connection_id is None and anchor.source_point is None and anchor.target_point is None and not anchor.points
            and anchor.line_shape is None
        ):
            raise RuleError("A line anchor must fix an end, a vertex or a shape.", 400)
        if anchor.source_element_id not in placed or anchor.target_element_id not in placed:
            raise RuleError("A line anchor must join two elements placed on the diagram.", 400)
        if anchor.connection_id is not None:
            if anchor.connection_id in seen_connections:
                raise RuleError("A connection can have one route.", 400)
            seen_connections.add(anchor.connection_id)
            continue
        key = frozenset((anchor.source_element_id, anchor.target_element_id))
        if key in seen:
            raise RuleError("A line can have one anchor.", 400)
        seen.add(key)
    if seen_connections:
        own = set(db.scalars(select(ArchitectureConnection.id).where(
            ArchitectureConnection.id.in_(seen_connections), ArchitectureConnection.project_id == project_id,
        )))
        if own != seen_connections:
            raise RuleError("A route can be set for a connection of this project.", 400)


def _route_values(anchor: AnchorIn | ArchitectureDiagramAnchor) -> tuple[Any, ...]:
    """What makes an anchor what it is, for comparing a stored one with a submitted one: both ends, the vertices and the shape."""
    points = [{"x": float(p["x"]), "y": float(p["y"])} if isinstance(p, dict) else {"x": p.x, "y": p.y} for p in anchor.points]
    return (
        anchor.source_point.value if isinstance(anchor.source_point, AttachPoint) else anchor.source_point,
        anchor.target_point.value if isinstance(anchor.target_point, AttachPoint) else anchor.target_point,
        points, _value(anchor.line_shape),
    )


def _anchor_key(anchor: AnchorIn | ArchitectureDiagramAnchor) -> tuple[Any, ...]:
    """What an anchor is for: its connection (one route each) or, for a pair's route, the two boxes."""
    if anchor.connection_id is not None:
        return ("connection", anchor.connection_id)
    return ("pair", anchor.source_element_id, anchor.target_element_id)


def _sync_anchors(db: Session, diagram_id: uuid.UUID, wanted: Sequence[AnchorIn] | None, placed: set[uuid.UUID]) -> int:
    """Makes the stored anchors match `wanted` (`None` keeps them), after dropping any whose box is no longer placed.
    A connection's route is matched by its connection, a pair's by its two boxes in the order stored.
    Returns how many rows were added, removed or changed."""
    changed = 0
    stored = anchors_of(db, diagram_id)
    keep: dict[tuple[Any, ...], ArchitectureDiagramAnchor] = {}
    for row in stored:
        if row.source_element_id not in placed or row.target_element_id not in placed:
            db.delete(row)
            changed += 1
        else:
            keep[_anchor_key(row)] = row
    if wanted is None:
        return changed
    given = {_anchor_key(a): a for a in wanted}
    for key, row in keep.items():
        a = given.get(key)
        if a is None:
            db.delete(row)
            changed += 1
        elif _route_values(row) != _route_values(a) or (row.source_element_id, row.target_element_id) != (a.source_element_id, a.target_element_id):
            row.source_element_id, row.target_element_id = a.source_element_id, a.target_element_id
            row.source_point = a.source_point.value if a.source_point else None
            row.target_point = a.target_point.value if a.target_point else None
            row.points = [{"x": p.x, "y": p.y} for p in a.points]
            row.line_shape = _value(a.line_shape)
            changed += 1
    for key, a in given.items():
        if key not in keep:
            db.add(ArchitectureDiagramAnchor(
                diagram_id=diagram_id, source_element_id=a.source_element_id, target_element_id=a.target_element_id,
                connection_id=a.connection_id,
                source_point=a.source_point.value if a.source_point else None,
                target_point=a.target_point.value if a.target_point else None,
                points=[{"x": p.x, "y": p.y} for p in a.points], line_shape=_value(a.line_shape),
            ))
            changed += 1
    return changed


def leaders_of(db: Session, note_ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, list[ArchitectureNoteLeader]]:
    """The leaders of the given notes in one read, by note, each list in order."""
    ids = list(note_ids)
    found: dict[uuid.UUID, list[ArchitectureNoteLeader]] = {}
    if not ids:
        return found
    for row in db.scalars(
        select(ArchitectureNoteLeader).where(ArchitectureNoteLeader.note_id.in_(ids))
        .order_by(ArchitectureNoteLeader.sort_order, ArchitectureNoteLeader.id)
    ):
        found.setdefault(row.note_id, []).append(row)
    return found


def _note_values(note: ArchitectureDiagramNote | NoteIn, order: int) -> tuple[Any, ...]:
    """What makes a note what it is (its block, tone, title, alignment and size mode), for comparing a stored note with a
    submitted one at position `order`. Its leaders are compared on their own."""
    return (
        note.text, note.x, note.y, note.width, note.height, order, _value(note.tone), note.title, _value(note.text_align),
        _value(note.size_mode),
    )


def _points_of(points: Iterable[Any]) -> list[dict[str, float]]:
    """A line's vertices as stored: `{x, y}` floats, from stored dictionaries or submitted `WaypointIn`s."""
    return [
        {"x": float(p["x"]), "y": float(p["y"])} if isinstance(p, dict) else {"x": float(p.x), "y": float(p.y)} for p in points
    ]


def _value(member: Any) -> Any:
    """The plain value of an enum member (a stored column already is one)."""
    return member.value if isinstance(member, enum.Enum) else member


def _leader_values(leader: ArchitectureNoteLeader | LeaderIn, order: int) -> tuple[Any, ...]:
    """What makes a leader what it is, for comparing a stored one with a submitted one at position `order`."""
    return (
        _value(leader.kind), leader.element_id, leader.connection_id, leader.state_id, leader.transition_id, leader.x, leader.y,
        _value(leader.start_point),
        _points_of(leader.points), _value(leader.line_shape), _value(leader.start_style), _value(leader.end_style), order,
    )


def leader_out(leader: ArchitectureNoteLeader) -> LeaderOut:
    """A stored leader as the view gives it."""
    return LeaderOut(
        id=leader.id, kind=LeaderKind(leader.kind), element_id=leader.element_id, connection_id=leader.connection_id,
        state_id=leader.state_id, transition_id=leader.transition_id, x=leader.x, y=leader.y,
        start_point=AttachPoint(leader.start_point) if leader.start_point else None,
        points=[WaypointIn(x=p["x"], y=p["y"]) for p in leader.points],
        line_shape=LineShape(leader.line_shape) if leader.line_shape else None,
        start_style=LineEnd(leader.start_style), end_style=LineEnd(leader.end_style),
    )


def note_out(note: ArchitectureDiagramNote, leaders: Sequence[ArchitectureNoteLeader] = ()) -> NoteOut:
    """A stored note with its leaders (read them with `leaders_of`) as the view gives it."""
    return NoteOut(
        id=note.id, title=note.title, text=note.text, x=note.x, y=note.y, width=note.width, height=note.height,
        tone=NoteTone(note.tone), text_align=NoteAlign(note.text_align), size_mode=NoteSizeMode(note.size_mode),
        leaders=[leader_out(row) for row in leaders],
    )


def _write_note(row: ArchitectureDiagramNote, note: NoteIn, order: int) -> None:
    """Copies a submitted note's block, tone, title, alignment and size mode onto its row."""
    row.text, row.x, row.y, row.width, row.height, row.sort_order = note.text, note.x, note.y, note.width, note.height, order
    row.tone, row.title, row.text_align = note.tone.value, note.title, note.text_align.value
    row.size_mode = note.size_mode.value


def _write_leader(row: ArchitectureNoteLeader, leader: LeaderIn, order: int) -> None:
    """Copies a submitted leader onto its row; the columns of the other target kinds are emptied, as the table requires."""
    kind = leader.kind
    row.sort_order, row.kind = order, kind.value
    row.element_id = leader.element_id if kind == LeaderKind.ELEMENT else None
    row.connection_id = leader.connection_id if kind == LeaderKind.CONNECTION else None
    row.state_id = leader.state_id if kind == LeaderKind.STATE else None
    row.transition_id = leader.transition_id if kind == LeaderKind.TRANSITION else None
    row.x = leader.x if kind == LeaderKind.POINT else None
    row.y = leader.y if kind == LeaderKind.POINT else None
    row.start_point = leader.start_point.value if leader.start_point else None
    row.points = _points_of(leader.points)
    row.line_shape = _value(leader.line_shape)
    row.start_style, row.end_style = leader.start_style.value, leader.end_style.value


def _check_leaders(
    db: Session, project_id: uuid.UUID, notes: Sequence[NoteIn], stored: dict[uuid.UUID, list[ArchitectureNoteLeader]],
    placed: set[uuid.UUID],
) -> None:
    """Checks what the notes' leaders point at. A new target element must be placed on the diagram and a new target
    connection must belong to its project, so a leader cannot name another owner's record; a target the leader already had
    is kept as it is (an element taken off the diagram, or retired, leaves the leader hidden, not rejected). A leader id
    must be one of its own note's, and listed once.

    Raises:
        RuleError: 400 for a leader to an element not on the diagram, a connection of another project, or a leader that is
            not the note's own or is listed twice.
    """
    new_connections: set[uuid.UUID] = set()
    for note in notes:
        before = {row.id: row for row in stored.get(note.id, [])} if note.id is not None else {}
        seen: set[uuid.UUID] = set()
        for leader in note.leaders:
            old = None
            if leader.id is not None:
                old = before.get(leader.id)
                if old is None or leader.id in seen:
                    raise RuleError("A leader does not belong to this note, or is listed twice.", 400)
                seen.add(leader.id)
            if leader.kind in (LeaderKind.STATE, LeaderKind.TRANSITION):
                raise RuleError("A note on a block diagram points at an element, a connection or a point.", 400)
            if leader.kind == LeaderKind.ELEMENT and leader.element_id is not None:
                if not (old is not None and old.element_id == leader.element_id) and leader.element_id not in placed:
                    raise RuleError("A note can point at an element that is on the diagram.", 400)
            elif leader.kind == LeaderKind.CONNECTION and leader.connection_id is not None:
                if not (old is not None and old.connection_id == leader.connection_id):
                    new_connections.add(leader.connection_id)
    if new_connections:
        own = set(db.scalars(select(ArchitectureConnection.id).where(
            ArchitectureConnection.id.in_(new_connections), ArchitectureConnection.project_id == project_id,
        )))
        if own != new_connections:
            raise RuleError("A note can point at a connection of this project.", 400)


def _sync_leaders(db: Session, note_id: uuid.UUID, wanted: Sequence[LeaderIn], stored: Sequence[ArchitectureNoteLeader]) -> int:
    """Makes the note's stored leaders match `wanted`; returns how many rows were added, removed or changed."""
    changed = 0
    existing = {row.id: row for row in stored}
    keep = {leader.id for leader in wanted if leader.id is not None}
    for leader_id, row in existing.items():
        if leader_id not in keep:
            db.delete(row)
            changed += 1
    for order, leader in enumerate(wanted):
        stored_row = existing.get(leader.id) if leader.id is not None else None
        if stored_row is None:
            created = ArchitectureNoteLeader(note_id=note_id)
            _write_leader(created, leader, order)
            db.add(created)
            changed += 1
        elif _leader_values(stored_row, stored_row.sort_order) != _leader_values(leader, order):
            _write_leader(stored_row, leader, order)
            changed += 1
    return changed


def sync_notes(
    db: Session, wanted: Sequence[NoteIn], stored: Sequence[ArchitectureDiagramNote],
    create: Callable[[], ArchitectureDiagramNote],
    check_leaders: Callable[[Sequence[NoteIn], dict[uuid.UUID, list[ArchitectureNoteLeader]]], None],
) -> int:
    """Makes a diagram's stored notes (and their leaders) match `wanted`, the whole list: a note left out is deleted, one
    without an id is created. The one routine behind both diagram types' layout saves; the owner supplies how a new row
    names it (`create`) and what its leaders may point at (`check_leaders`, which raises `RuleError`). Returns how many
    note and leader rows were added, removed or changed. The caller commits.

    Raises:
        RuleError: 400 for a note id that is not the diagram's, a note listed twice, a block that is not finite, or what
            `check_leaders` refuses.
    """
    kept = {n.id: n for n in stored}
    for note in wanted:
        _check_box(note)
        if note.id is not None and note.id not in kept:
            raise RuleError("A note does not belong to this diagram.", 400)
    note_ids = [n.id for n in wanted if n.id is not None]
    if len(set(note_ids)) != len(note_ids):
        raise RuleError("A note can be listed once.", 400)
    stored_leaders = leaders_of(db, kept)
    check_leaders(wanted, stored_leaders)
    changed = 0
    for note_id, old_note in kept.items():
        if note_id not in set(note_ids):
            db.delete(old_note)
            changed += 1
    rows: list[ArchitectureDiagramNote] = []
    for order, note in enumerate(wanted):
        note_row = kept.get(note.id) if note.id is not None else None
        if note_row is None:
            note_row = create()
            _write_note(note_row, note, order)
            db.add(note_row)
            changed += 1
        elif _note_values(note_row, note_row.sort_order) != _note_values(note, order):
            _write_note(note_row, note, order)
            changed += 1
        rows.append(note_row)
    db.flush()  # a leader row names its note, so the notes are written first
    for note_row, note in zip(rows, wanted, strict=True):
        changed += _sync_leaders(db, note_row.id, note.leaders, stored_leaders.get(note_row.id, []))
    return changed


def _box(row: ArchitectureDiagramPlacement | ArchitectureDiagramNote) -> tuple[float, float, float, float]:
    return (row.x, row.y, row.width, row.height)


def save_layout(
    db: Session, project: Any, actor: User, diagram_id: uuid.UUID, payload: LayoutSave,
) -> ArchitectureDiagram:
    """Replaces the diagram's placements, notes and (when given) line anchors and boundary boxes with the lists given.
    The caller commits.

    Elements already placed stay (even if now retired or unreadable); each newly placed element must pass
    `_check_new_element`. An element left out is unplaced, never deleted, and its line anchors go with it. Nothing
    changes (and the version does not advance) when the lists equal what is stored.

    Raises:
        RuleError: 404 if absent, 409 on a stale `version`, 400 for a repeated or unavailable element, a note id that
            is not this diagram's, a box that is not finite, an anchor that is not between two placed elements, or a
            new boundary box that is not for an open outer connection of the diagram's scope.
    """
    diagram = get_diagram(db, project.id, diagram_id, lock=True)
    _check_version(diagram, payload.version)
    wanted_ids = [p.element_id for p in payload.placements]
    if len(set(wanted_ids)) != len(wanted_ids):
        raise RuleError("An element can be placed on a diagram once.", 400)
    boxes: list[PlacementIn | NoteIn] = [*payload.placements, *payload.notes]
    for box in boxes:
        _check_box(box)
    if payload.anchors is not None:
        _check_anchors(db, project.id, payload.anchors, set(wanted_ids))
    existing = {p.element_id: p for p in placements_of(db, diagram.id)}
    _check_new_element(db, Viewer.of_user(actor, project), [e for e in wanted_ids if e not in existing])
    if payload.boundaries is not None:
        for boundary_box in payload.boundaries:
            _check_box(boundary_box)
        boundary_rules.check_boundaries(
            db, project.id, diagram.scope_element_id, payload.boundaries,
            {b.connection_id: b for b in boundary_rules.boundaries_of(db, diagram.id)},
        )

    added = removed = moved = 0
    for element_id, old in existing.items():
        if element_id not in set(wanted_ids):
            db.delete(old)
            removed += 1
    for placement in payload.placements:
        row = existing.get(placement.element_id)
        if row is None:
            db.add(ArchitectureDiagramPlacement(
                diagram_id=diagram.id, element_id=placement.element_id, x=placement.x, y=placement.y,
                width=placement.width, height=placement.height, collapsed=placement.collapsed,
            ))
            added += 1
        elif _box(row) != (placement.x, placement.y, placement.width, placement.height) or row.collapsed != placement.collapsed:
            row.x, row.y, row.width, row.height, row.collapsed = (
                placement.x, placement.y, placement.width, placement.height, placement.collapsed,
            )
            moved += 1

    notes_changed = sync_notes(
        db, payload.notes, notes_of(db, diagram.id), lambda: ArchitectureDiagramNote(id=uuid.uuid4(), diagram_id=diagram.id),
        lambda notes, stored: _check_leaders(db, project.id, notes, stored, set(wanted_ids)),
    )

    anchors_changed = _sync_anchors(db, diagram.id, payload.anchors, set(wanted_ids))
    boundaries_changed = boundary_rules.sync_boundaries(db, diagram.id, payload.boundaries)

    if not (added or removed or moved or notes_changed or anchors_changed or boundaries_changed):
        return diagram
    diagram.version += 1
    db.flush()
    _audit(
        db, diagram.id, "layout_saved", actor, project.id,
        placements_added=added, placements_removed=removed, placements_moved=moved, notes_changed=notes_changed,
        anchors_changed=anchors_changed, boundaries_changed=boundaries_changed,
    )
    return diagram


def add_placement(
    db: Session, project: Any, actor: User, diagram_id: uuid.UUID, version: int, placement: PlacementIn,
) -> ArchitectureDiagram:
    """Places one more element on a diagram. The caller commits.

    Raises:
        RuleError: 404 if absent, 409 on a stale version, 400 if the element is already placed or not available.
    """
    diagram = get_diagram(db, project.id, diagram_id, lock=True)
    _check_version(diagram, version)
    _check_box(placement)
    if db.scalar(select(ArchitectureDiagramPlacement.id).where(
        ArchitectureDiagramPlacement.diagram_id == diagram.id, ArchitectureDiagramPlacement.element_id == placement.element_id,
    )):
        raise RuleError("This element is already on the diagram.", 400)
    _check_new_element(db, Viewer.of_user(actor, project), [placement.element_id])
    db.add(ArchitectureDiagramPlacement(
        diagram_id=diagram.id, element_id=placement.element_id, x=placement.x, y=placement.y, width=placement.width,
        height=placement.height, collapsed=placement.collapsed,
    ))
    diagram.version += 1
    db.flush()
    _audit(db, diagram.id, "layout_saved", actor, project.id, placements_added=1)
    return diagram


def remove_placement(
    db: Session, project_id: uuid.UUID, actor: User, diagram_id: uuid.UUID, version: int, element_id: uuid.UUID,
) -> ArchitectureDiagram:
    """Takes an element off a diagram; the element itself is untouched. The caller commits.

    Raises:
        RuleError: 404 if the diagram is absent or the element is not on it, 409 on a stale version.
    """
    diagram = get_diagram(db, project_id, diagram_id, lock=True)
    _check_version(diagram, version)
    row = db.scalar(select(ArchitectureDiagramPlacement).where(
        ArchitectureDiagramPlacement.diagram_id == diagram.id, ArchitectureDiagramPlacement.element_id == element_id,
    ))
    if row is None:
        raise RuleError("This element is not on the diagram.", 404)
    db.delete(row)
    anchors = [a for a in anchors_of(db, diagram.id) if element_id in (a.source_element_id, a.target_element_id)]
    for anchor in anchors:
        db.delete(anchor)
    diagram.version += 1
    db.flush()
    _audit(db, diagram.id, "layout_saved", actor, project_id, placements_removed=1, anchors_changed=len(anchors))
    return diagram


# --- Toggles ---------------------------------------------------------------


def toggles_of(db: Session, diagram_id: uuid.UUID) -> list[ArchitectureDiagramToggle]:
    """The diagram's toggles in order."""
    return list(db.scalars(
        select(ArchitectureDiagramToggle).where(ArchitectureDiagramToggle.diagram_id == diagram_id)
        .order_by(ArchitectureDiagramToggle.sort_order, ArchitectureDiagramToggle.name)
    ))


def toggle_members(db: Session, toggle_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, list[ArchitectureDiagramToggleMember]]:
    """`{toggle id: its manual members}` in one statement."""
    found: dict[uuid.UUID, list[ArchitectureDiagramToggleMember]] = {}
    if toggle_ids:
        for member in db.scalars(
            select(ArchitectureDiagramToggleMember).where(ArchitectureDiagramToggleMember.toggle_id.in_(toggle_ids))
            .order_by(ArchitectureDiagramToggleMember.created_at, ArchitectureDiagramToggleMember.id)
        ):
            found.setdefault(member.toggle_id, []).append(member)
    return found


def _usable_type_ids(db: Session, project: Any) -> tuple[set[uuid.UUID], set[uuid.UUID], set[uuid.UUID]]:
    """The element type, connection type and domain ids a toggle rule may name: the project's effective rows, its own, and
    its organisation's (a row a hidden default still holds)."""
    def ids(vocabulary: Any) -> set[uuid.UUID]:
        rows = [
            *vocabulary.resolve_effective(db, project.id, project.organization_id).rows,
            *vocabulary.project_rows(db, project.id), *vocabulary.org_rows(db, project.organization_id),
        ]
        return {r.id for r in rows}

    return ids(ELEMENT_TYPES), ids(CONNECTION_TYPES), ids(DOMAINS)


def _clean_rule(rule: Any) -> dict[str, list[str]]:
    """A rule as stored: ids as strings, tags trimmed and de-duplicated (empty lists dropped)."""
    tags = list(dict.fromkeys(t.strip() for t in rule.tags if t.strip()))
    if any(len(t) > 100 for t in tags):
        raise RuleError("A tag name in a rule can be at most 100 characters.", 400)
    cleaned = {
        "element_type_ids": [str(i) for i in dict.fromkeys(rule.element_type_ids)],
        "connection_type_ids": [str(i) for i in dict.fromkeys(rule.connection_type_ids)],
        "domain_ids": [str(i) for i in dict.fromkeys(rule.domain_ids)],
        "tags": tags,
    }
    return {key: value for key, value in cleaned.items() if value}


def save_toggles(
    db: Session, project: Any, actor: User, diagram_id: uuid.UUID, payload: TogglesSave,
) -> ArchitectureDiagram:
    """Replaces the diagram's toggles with the list given. The caller commits.

    Raises:
        RuleError: 404 if absent, 409 on a stale `version`, 400 for a repeated name, a toggle id that is not this
            diagram's, a rule naming a type the project cannot use, or a member the person cannot read.
    """
    diagram = get_diagram(db, project.id, diagram_id, lock=True)
    _check_version(diagram, payload.version)
    names = [t.name.strip().lower() for t in payload.toggles]
    if len(set(names)) != len(names):
        raise RuleError("Two toggles of a diagram cannot share a name.", 400)
    existing = {t.id: t for t in toggles_of(db, diagram.id)}
    for toggle in payload.toggles:
        if toggle.id is not None and toggle.id not in existing:
            raise RuleError("A toggle does not belong to this diagram.", 400)
    given_ids = [t.id for t in payload.toggles if t.id is not None]
    if len(set(given_ids)) != len(given_ids):
        raise RuleError("A toggle can be listed once.", 400)
    element_types, connection_types, domains = _usable_type_ids(db, project)
    viewer = Viewer.of_user(actor, project)
    wanted_elements = {e for t in payload.toggles for e in t.element_ids}
    readable = visible_element_ids(db, viewer, wanted_elements)
    wanted_connections = {c for t in payload.toggles for c in t.connection_ids}
    own_connections = set(db.scalars(select(ArchitectureConnection.id).where(
        ArchitectureConnection.id.in_(wanted_connections), ArchitectureConnection.project_id == project.id,
    ))) if wanted_connections else set()
    for toggle in payload.toggles:
        if not set(toggle.rule.element_type_ids) <= element_types or not set(toggle.rule.connection_type_ids) <= connection_types:
            raise RuleError("A rule names a type this project cannot use.", 400)
        if not set(toggle.rule.domain_ids) <= domains:
            raise RuleError("A rule names a domain this project cannot use.", 400)
        if not set(toggle.element_ids) <= readable or not set(toggle.connection_ids) <= own_connections:
            raise RuleError("A toggle names an element or connection that is not available for this project.", 400)

    for toggle_id, old in existing.items():
        if toggle_id not in set(given_ids):
            db.delete(old)
        else:
            # Park the name so renames that swap two toggles' names cannot collide while they are applied.
            old.name = str(old.id)
    db.flush()
    for order, toggle in enumerate(payload.toggles):
        found = existing.get(toggle.id) if toggle.id is not None else None
        rule = _clean_rule(toggle.rule)
        if found is None:
            row = ArchitectureDiagramToggle(
                diagram_id=diagram.id, name=toggle.name.strip(), default_on=toggle.default_on, rule=rule, sort_order=order,
            )
            db.add(row)
        else:
            row = found
            row.name, row.default_on, row.rule, row.sort_order = toggle.name.strip(), toggle.default_on, rule, order
        db.flush()
        _replace_members(db, row, toggle)
    diagram.version += 1
    db.flush()
    _audit(db, diagram.id, "toggles_saved", actor, project.id, toggles=len(payload.toggles))
    return diagram


def _replace_members(db: Session, row: ArchitectureDiagramToggle, toggle: ToggleIn) -> None:
    """Makes the toggle's manual members exactly the elements and connections named (duplicates ignored)."""
    current = toggle_members(db, [row.id]).get(row.id, [])
    want_elements, want_connections = set(toggle.element_ids), set(toggle.connection_ids)
    have_elements = {m.element_id for m in current if m.element_id is not None}
    have_connections = {m.connection_id for m in current if m.connection_id is not None}
    for member in current:
        if (member.element_id is not None and member.element_id not in want_elements) or (
            member.connection_id is not None and member.connection_id not in want_connections
        ):
            db.delete(member)
    for element_id in want_elements - have_elements:
        db.add(ArchitectureDiagramToggleMember(toggle_id=row.id, element_id=element_id))
    for connection_id in want_connections - have_connections:
        db.add(ArchitectureDiagramToggleMember(toggle_id=row.id, connection_id=connection_id))
    db.flush()


# --- API shape (bulk) ------------------------------------------------------


def diagram_outs(db: Session, diagrams: Sequence[ArchitectureDiagram], viewer: Viewer) -> list[DiagramOut]:
    """API shapes for `diagrams`: counts and scope elements are read in bulk, so the cost does not grow with the list."""
    ids = [d.id for d in diagrams]
    moves = ProjectMoves(db, DIAGRAM_ARTEFACT_TYPE)

    def counts(model: Any) -> dict[uuid.UUID, int]:
        if not ids:
            return {}
        return {
            diagram_id: count for diagram_id, count in db.execute(
                select(model.diagram_id, func.count()).where(model.diagram_id.in_(ids)).group_by(model.diagram_id)
            ).tuples()
        }

    placements = counts(ArchitectureDiagramPlacement)
    notes = counts(ArchitectureDiagramNote)
    toggles = counts(ArchitectureDiagramToggle)
    paths = folder_paths(db, (d.folder_id for d in diagrams))
    scope_ids = {d.scope_element_id for d in diagrams if d.scope_element_id is not None}
    readable = visible_element_ids(db, viewer, scope_ids)
    scopes = {
        e.id: e for e in db.scalars(select(ArchitectureElement).where(ArchitectureElement.id.in_(scope_ids)))
    } if scope_ids else {}
    return [
        DiagramOut(
            id=d.id, project_id=d.project_id, unique_code=d.unique_code, name=d.name, purpose=d.purpose,
            scope_element_id=d.scope_element_id,
            scope_element_code=scopes[d.scope_element_id].unique_code if d.scope_element_id in scopes else None,
            scope_element_name=scopes[d.scope_element_id].name if d.scope_element_id in readable else (
                "" if d.scope_element_id in scopes else None
            ),
            connection_detail=d.connection_detail, line_hops=d.line_hops, show_connection_names=d.show_connection_names,
            line_shape=LineShape(d.line_shape), folder_id=d.folder_id,
            folder_path=paths.get(d.folder_id) if d.folder_id else None, status=d.status, allowed_status_moves=moves.of(d.project_id, d.status),
            version=d.version, creator_id=d.creator_id,
            is_archived=d.is_archived, archived_at=d.archived_at, created_at=d.created_at, updated_at=d.updated_at,
            placement_count=placements.get(d.id, 0), note_count=notes.get(d.id, 0), toggle_count=toggles.get(d.id, 0),
        )
        for d in diagrams
    ]
