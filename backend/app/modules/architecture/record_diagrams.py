"""
Module: modules.architecture.record_diagrams

The diagrams an element or a connection appears on, for the Diagrams card of its page.

Responsibilities:
- List the block diagrams that draw a record and, for an element, the state machine diagrams that describe it, in one
  read per record: placements, diagrams, ancestors and names are loaded in bulk, so the statements do not grow with the
  number of diagrams.
- Say how the record appears: its own box, inside a drawn ancestor, a line, a line rolled up to ancestors.

Design decisions:
- **A connection is drawn where `diagram_resolver.resolve` would draw it**, run over that one connection and each
  diagram's placed elements, so a rolled-up line follows the one rule the diagram itself uses. View toggles are a view
  state and are not applied, so a diagram that can draw the line lists it even while a toggle hides it.
- **Visibility follows the caller's gates, not new ones.** The route reads the record through the visibility resolver
  (a hidden record is a 404) and passes which of the two sub-components the caller may read; a diagram type whose
  sub-component is off is absent, indistinguishable from none. An ancestor's name the caller cannot read is blank.
- **Archived diagrams are left out**, as the diagram and state machine lists leave them out.

Dependencies: `diagram_resolver`, `visibility`, `models`, `schemas`.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.architecture.diagram_resolver import ModelConnection, resolve
from app.modules.architecture.models import (
    ArchitectureConnection,
    ArchitectureDiagram,
    ArchitectureDiagramPlacement,
    ArchitectureElement,
    ArchitectureStateMachineDiagram,
)
from app.modules.architecture.schemas import RecordDiagramOut
from app.modules.architecture.visibility import Viewer, ancestor_parents, visible_element_ids

BLOCK = "block"
STATE_MACHINE = "state_machine"

#: How a record appears on a diagram (`RecordDiagramOut.usage`).
PLACED, INSIDE, DRAWN, ROLLED_UP, DESCRIBES = "placed", "inside", "drawn", "rolled_up", "describes"

_CHAIN_CAP = 64


def _chain(parents: dict[uuid.UUID, uuid.UUID | None], element_id: uuid.UUID) -> list[uuid.UUID]:
    """The element and its ancestors, nearest first (cycle-safe and capped)."""
    chain: list[uuid.UUID] = []
    node: uuid.UUID | None = element_id
    while node is not None and node not in chain and len(chain) < _CHAIN_CAP:
        chain.append(node)
        node = parents.get(node)
    return chain


def _placements(db: Session, project_id: uuid.UUID, element_ids: Iterable[uuid.UUID]) -> list[tuple[ArchitectureDiagram, uuid.UUID]]:
    """`(diagram, placed element id)` for each open diagram of the project that places one of `element_ids`."""
    wanted = list(element_ids)
    if not wanted:
        return []
    rows = db.execute(
        select(ArchitectureDiagram, ArchitectureDiagramPlacement.element_id)
        .join(ArchitectureDiagramPlacement, ArchitectureDiagramPlacement.diagram_id == ArchitectureDiagram.id)
        .where(
            ArchitectureDiagram.project_id == project_id, ArchitectureDiagram.is_archived.is_(False),
            ArchitectureDiagramPlacement.element_id.in_(wanted),
        )
    ).tuples().all()
    return list(rows)


def _out(
    diagram: ArchitectureDiagram | ArchitectureStateMachineDiagram, kind: str, usage: str,
    via: tuple[uuid.UUID, str, str] | None = None,
) -> RecordDiagramOut:
    """The API shape of one listed diagram; `via` is the drawn ancestor's `(id, code, name)` for `inside`."""
    return RecordDiagramOut(
        id=diagram.id, kind=kind, unique_code=diagram.unique_code, name=diagram.name, status=diagram.status, usage=usage,
        via_element_id=via[0] if via else None, via_element_code=via[1] if via else None,
        via_element_name=via[2] if via else None,
    )


def _ordered(rows: list[RecordDiagramOut]) -> list[RecordDiagramOut]:
    """Block diagrams, then state machine diagrams, each by code."""
    return sorted(rows, key=lambda r: (r.kind != BLOCK, r.unique_code))


def element_diagrams(
    db: Session, viewer: Viewer, project_id: uuid.UUID, element: ArchitectureElement, *, blocks: bool, machines: bool,
) -> list[RecordDiagramOut]:
    """The diagrams that draw or describe `element` in the project.

    Args:
        db: Session.
        viewer: Who is reading (names of ancestors they may not read are blank).
        project_id: The project whose diagrams are listed.
        element: An element the viewer may read.
        blocks: Whether block diagrams are offered (the diagram sub-component is on).
        machines: Whether state machine diagrams are offered (the state machine sub-component is on).

    Returns:
        Block diagrams (placed, or inside a drawn ancestor) then state machine diagrams, each by code.
    """
    found: list[RecordDiagramOut] = []
    if blocks:
        chain = _chain(ancestor_parents(db, [element.id]), element.id)
        nearest: dict[uuid.UUID, tuple[int, ArchitectureDiagram]] = {}
        for diagram, placed_id in _placements(db, project_id, chain):
            depth = chain.index(placed_id)
            if diagram.id not in nearest or depth < nearest[diagram.id][0]:
                nearest[diagram.id] = (depth, diagram)
        via_ids = {chain[depth] for depth, _d in nearest.values() if depth > 0}
        names = _names(db, viewer, via_ids)
        for depth, diagram in nearest.values():
            if depth == 0:
                found.append(_out(diagram, BLOCK, PLACED))
                continue
            code, name = names.get(chain[depth], ("", ""))
            found.append(_out(diagram, BLOCK, INSIDE, (chain[depth], code, name)))
    if machines:
        for machine in db.scalars(select(ArchitectureStateMachineDiagram).where(
            ArchitectureStateMachineDiagram.project_id == project_id, ArchitectureStateMachineDiagram.element_id == element.id,
            ArchitectureStateMachineDiagram.is_archived.is_(False),
        )):
            found.append(_out(machine, STATE_MACHINE, DESCRIBES))
    return _ordered(found)


def connection_diagrams(db: Session, project_id: uuid.UUID, connection: ArchitectureConnection) -> list[RecordDiagramOut]:
    """The block diagrams that draw `connection`, as a line between its ends or between ancestors of them.

    Args:
        db: Session.
        project_id: The project whose diagrams are listed.
        connection: A connection of the project.

    Returns:
        The diagrams by code, `drawn` or `rolled_up`.
    """
    ends = (connection.source_element_id, connection.target_element_id)
    parents = ancestor_parents(db, ends)
    candidates = {a for end in ends for a in _chain(parents, end)}
    placed_by_diagram: dict[uuid.UUID, set[uuid.UUID]] = {}
    diagrams: dict[uuid.UUID, ArchitectureDiagram] = {}
    for diagram, placed_id in _placements(db, project_id, candidates):
        diagrams[diagram.id] = diagram
        placed_by_diagram.setdefault(diagram.id, set()).add(placed_id)
    line_of = ModelConnection(connection.id, ends[0], ends[1], directional=True)
    found: list[RecordDiagramOut] = []
    for diagram_id, placed in placed_by_diagram.items():
        lines = resolve(placed=placed, parents=parents, connections=[line_of], merge_parallel=False).lines
        if lines:
            found.append(_out(diagrams[diagram_id], BLOCK, ROLLED_UP if lines[0].rolled_up else DRAWN))
    return _ordered(found)


def _names(db: Session, viewer: Viewer, element_ids: set[uuid.UUID]) -> dict[uuid.UUID, tuple[str, str]]:
    """`{element id: (code, name)}`, the name blank for an element the viewer may not read."""
    if not element_ids:
        return {}
    readable = visible_element_ids(db, viewer, element_ids)
    return {
        e.id: (e.unique_code, e.name if e.id in readable else "")
        for e in db.scalars(select(ArchitectureElement).where(ArchitectureElement.id.in_(element_ids)))
    }
