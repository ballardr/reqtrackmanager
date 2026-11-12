"""
Module: modules.architecture.diagrams

The rules for diagrams and what they hold: create, edit, move between statuses, archive and delete a diagram; replace
its layout (placements and notes) or its toggles; place or unplace one element. The read side (the resolved view) is in
`diagram_view`.

Responsibilities:
- Validate every reference a diagram stores: a scope or placed element the viewer may read, a toggle member, a rule's
  types.
- Advance the diagram's `version` on every change to the diagram or to anything it holds, and write one audit event per
  change holding ids, counts and field names, never names or text.
- Read lists in bulk (`diagram_outs`): one statement per kind of related row however many diagrams are listed.

Design decisions:
- **A diagram is a view.** Deleting a diagram, or a placement, loses nothing from the model; deleting an element removes
  its placements (a database cascade). The model's own rules (an element another project uses cannot be deleted) are
  unchanged.
- **One lock for the whole diagram.** A save quotes the `version` it was based on, and the row is locked while it is
  checked. Moving a box and adding a toggle advance the same counter, so an editor holding a stale copy is told before it
  overwrites.
- **Who may be placed.** An element the viewer can read: the project's own, or one another owner shares with it. A
  retired shared element cannot be newly placed (as for a connection), but a placement already on the diagram is kept
  when the diagram is saved again, so a revoked or retired element never makes a diagram unsaveable. An archived element
  cannot be newly placed.
- **Layout save replaces.** The editor owns undo and redo, so it saves the complete placement and note lists; an element
  left out is unplaced. An id that names a note or toggle of another diagram is refused.
- **Toggle rules name vocabulary rows, domains and tag names, never records;** a toggle's manual members are the only
  record references, and each must be readable.

Dependencies: `records` (the shared rule errors, version lock and audit helpers), `visibility`, `service`, core
`services.sequences`, `services.tags`, `services.placements`, `services.audit`.
"""

from __future__ import annotations

import math
import uuid
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.user import User
from app.modules.architecture.enums import RecordStatus
from app.modules.architecture.models import (
    ArchitectureConnection,
    ArchitectureDiagram,
    ArchitectureDiagramNote,
    ArchitectureDiagramPlacement,
    ArchitectureDiagramToggle,
    ArchitectureDiagramToggleMember,
    ArchitectureElement,
)
from app.modules.architecture.records import (
    _NO_STATUS_CHANGE_NEEDED,
    RuleError,
    _check_version,
    _detail,
    _forget,
    _touch,
)
from app.modules.architecture.schemas import (
    DiagramCreate,
    DiagramOut,
    DiagramUpdate,
    LayoutSave,
    NoteIn,
    PlacementIn,
    ToggleIn,
    TogglesSave,
)
from app.modules.architecture.service import (
    CONNECTION_TYPES,
    DIAGRAM_ARTEFACT_TYPE,
    DIAGRAM_CODE_PREFIX,
    ELEMENT_TYPES,
)
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
        if element.project_id != viewer.project_id and element.status == RecordStatus.RETIRED.value:
            raise RuleError("A retired element of another owner cannot be newly added.", 400)


def _check_box(placement: PlacementIn | NoteIn) -> None:
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
    diagram = ArchitectureDiagram(
        project_id=project.id,
        unique_code=generate_unique_code(db, project, DIAGRAM_ARTEFACT_TYPE, DIAGRAM_CODE_PREFIX),
        name=payload.name.strip(), purpose=payload.purpose, scope_element_id=payload.scope_element_id,
        connection_detail=payload.connection_detail,
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
    if "scope_element_id" in given and payload.scope_element_id != diagram.scope_element_id:
        if payload.scope_element_id is not None:
            _check_new_element(db, Viewer.of_user(actor, project), [payload.scope_element_id])
        changes["scope_element_id"] = payload.scope_element_id
    if not changes:
        return diagram
    _touch(diagram, **changes)
    db.flush()
    _audit(db, diagram.id, "updated", actor, project.id, fields=sorted(changes))
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
    if diagram.status == status.value:
        raise RuleError(_NO_STATUS_CHANGE_NEEDED, 409)
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
    """The diagram's notes in order."""
    return list(db.scalars(
        select(ArchitectureDiagramNote).where(ArchitectureDiagramNote.diagram_id == diagram_id)
        .order_by(ArchitectureDiagramNote.sort_order, ArchitectureDiagramNote.id)
    ))


def _box(row: ArchitectureDiagramPlacement | ArchitectureDiagramNote) -> tuple[float, float, float, float]:
    return (row.x, row.y, row.width, row.height)


def save_layout(
    db: Session, project: Any, actor: User, diagram_id: uuid.UUID, payload: LayoutSave,
) -> ArchitectureDiagram:
    """Replaces the diagram's placements and notes with the lists given. The caller commits.

    Elements already placed stay (even if now retired or unreadable); each newly placed element must pass
    `_check_new_element`. An element left out is unplaced, never deleted. Nothing changes (and the version does not
    advance) when the lists equal what is stored.

    Raises:
        RuleError: 404 if absent, 409 on a stale `version`, 400 for a repeated or unavailable element, a note id that
            is not this diagram's, or a box that is not finite.
    """
    diagram = get_diagram(db, project.id, diagram_id, lock=True)
    _check_version(diagram, payload.version)
    wanted_ids = [p.element_id for p in payload.placements]
    if len(set(wanted_ids)) != len(wanted_ids):
        raise RuleError("An element can be placed on a diagram once.", 400)
    boxes: list[PlacementIn | NoteIn] = [*payload.placements, *payload.notes]
    for box in boxes:
        _check_box(box)
    existing = {p.element_id: p for p in placements_of(db, diagram.id)}
    _check_new_element(db, Viewer.of_user(actor, project), [e for e in wanted_ids if e not in existing])

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

    kept_notes = {n.id: n for n in notes_of(db, diagram.id)}
    for note in payload.notes:
        if note.id is not None and note.id not in kept_notes:
            raise RuleError("A note does not belong to this diagram.", 400)
    note_ids = {n.id for n in payload.notes if n.id is not None}
    if len(note_ids) != len([n for n in payload.notes if n.id is not None]):
        raise RuleError("A note can be listed once.", 400)
    notes_changed = 0
    for note_id, old_note in kept_notes.items():
        if note_id not in note_ids:
            db.delete(old_note)
            notes_changed += 1
    for order, note in enumerate(payload.notes):
        note_row = kept_notes.get(note.id) if note.id is not None else None
        if note_row is None:
            db.add(ArchitectureDiagramNote(
                diagram_id=diagram.id, text=note.text, x=note.x, y=note.y, width=note.width, height=note.height, sort_order=order,
            ))
            notes_changed += 1
        elif (note_row.text, *_box(note_row), note_row.sort_order) != (note.text, note.x, note.y, note.width, note.height, order):
            note_row.text, note_row.x, note_row.y, note_row.width, note_row.height, note_row.sort_order = (
                note.text, note.x, note.y, note.width, note.height, order,
            )
            notes_changed += 1

    if not (added or removed or moved or notes_changed):
        return diagram
    diagram.version += 1
    db.flush()
    _audit(
        db, diagram.id, "layout_saved", actor, project.id,
        placements_added=added, placements_removed=removed, placements_moved=moved, notes_changed=notes_changed,
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
    diagram.version += 1
    db.flush()
    _audit(db, diagram.id, "layout_saved", actor, project_id, placements_removed=1)
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


def _usable_type_ids(db: Session, project: Any) -> tuple[set[uuid.UUID], set[uuid.UUID]]:
    """The element type ids and connection type ids a toggle rule may name: the project's effective rows, its own, and
    its organisation's (a type a hidden default still holds)."""
    def ids(vocabulary: Any) -> set[uuid.UUID]:
        rows = [
            *vocabulary.resolve_effective(db, project.id, project.organization_id).rows,
            *vocabulary.project_rows(db, project.id), *vocabulary.org_rows(db, project.organization_id),
        ]
        return {r.id for r in rows}

    return ids(ELEMENT_TYPES), ids(CONNECTION_TYPES)


def _clean_rule(rule: Any) -> dict[str, list[str]]:
    """A rule as stored: ids as strings, domains as values, tags trimmed and de-duplicated (empty lists dropped)."""
    tags = list(dict.fromkeys(t.strip() for t in rule.tags if t.strip()))
    if any(len(t) > 100 for t in tags):
        raise RuleError("A tag name in a rule can be at most 100 characters.", 400)
    cleaned = {
        "element_type_ids": [str(i) for i in dict.fromkeys(rule.element_type_ids)],
        "connection_type_ids": [str(i) for i in dict.fromkeys(rule.connection_type_ids)],
        "domains": [d.value for d in dict.fromkeys(rule.domains)],
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
    element_types, connection_types = _usable_type_ids(db, project)
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
            connection_detail=d.connection_detail, status=d.status, version=d.version, creator_id=d.creator_id,
            is_archived=d.is_archived, archived_at=d.archived_at, created_at=d.created_at, updated_at=d.updated_at,
            placement_count=placements.get(d.id, 0), note_count=notes.get(d.id, 0), toggle_count=toggles.get(d.id, 0),
        )
        for d in diagrams
    ]
