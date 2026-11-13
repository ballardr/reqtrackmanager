"""
Module: modules.architecture.boundaries

The rules for the links between a layer and the layer above it: the boundary boxes a scoped diagram draws for the
*outer* connections of its scope, and the "realises" link that marks an inner connection as the lower layer's part of
an outer one.

Responsibilities:
- Say which connections are outer for a scope (`outer_sides`) and how a box is drawn (`shape_for`).
- Validate and store a connection's realisations (`set_realisations`; reading and pruning them is in `realisations`).
- Sync a diagram's boundary boxes from a layout save (`check_boundaries`, `sync_boundaries`).

Design decisions:
- **An outer connection is a connection with exactly one end in the scope's subtree** (the scope itself or a
  descendant); `diagram_resolver.outer_side` is the single definition, shared with the browser by a golden file.
- **A realisation is valid when** the two connections are different connections of one project, the inner connection
  lies inside the interface the outer one declares (`realisations.realises_rule_holds`: both ends inside one end of the
  outer connection, or each end inside a different end of it), and no cycle forms (two connections with the same ends
  could otherwise realise each other). The inner connection may be wholly inside the outer end (it covers the outer
  one), end at that element itself, or run from an inner element to the element outside; the last two are drawn to the
  outer connection's boundary box.
- **A stale box is kept, not deleted.** When an edit to the model makes a connection stop being outer for the diagram's
  scope, its box is simply not drawn, as a line anchor whose line is not drawn is kept.
- **Neutral wording.** A box is "covered" or "not covered" by a realisation; nothing here treats an uncovered box as an
  error.

Dependencies: `diagram_resolver`, `records` (rule errors, audit helpers), `visibility`; core `services.audit`.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.user import User
from app.modules.architecture.diagram_resolver import outer_side
from app.modules.architecture.enums import BoundaryShape
from app.modules.architecture.models import (
    ArchitectureConnection,
    ArchitectureConnectionRealisation,
    ArchitectureDiagramBoundary,
)
from app.modules.architecture.realisations import project_realisations, reaches, realises_rule_holds
from app.modules.architecture.records import RuleError, _audit_connection, get_connection
from app.modules.architecture.schemas import BoundaryIn
from app.modules.architecture.visibility import ancestor_parents

#: The most connections one connection may realise (a bound on the request, not a modelling limit).
MAX_REALISATIONS = 50


# --- Outer connections ------------------------------------------------------


def outer_sides(
    db: Session, scope_id: uuid.UUID, connections: Sequence[ArchitectureConnection],
) -> dict[uuid.UUID, uuid.UUID]:
    """`{connection id: its scope-side end element}` for the connections that are outer for `scope_id` (one query for
    the whole tree walk, however many connections are given)."""
    ends = {e for c in connections for e in (c.source_element_id, c.target_element_id)}
    parents = ancestor_parents(db, ends)
    found: dict[uuid.UUID, uuid.UUID] = {}
    for c in connections:
        side = outer_side(scope_id, parents, c.source_element_id, c.target_element_id)
        if side is not None:
            found[c.id] = side
    return found


def shape_for(directional: bool, scope_end_is_source: bool, outside_readable: bool) -> BoundaryShape:
    """How a boundary box is drawn.

    Args:
        directional: Whether the outer connection's type is one-way.
        scope_end_is_source: Whether the scope-side end is the connection's source (the scope sends).
        outside_readable: Whether the viewer may read the element outside; when not, no direction is disclosed.

    Returns:
        `OUTPUT` when the scope sends, `INPUT` when it receives, `BIDIRECTIONAL` for a two-way connection and `DOT`
        when the outside element is not readable.
    """
    if not outside_readable:
        return BoundaryShape.DOT
    if not directional:
        return BoundaryShape.BIDIRECTIONAL
    return BoundaryShape.OUTPUT if scope_end_is_source else BoundaryShape.INPUT


# --- Realisations -----------------------------------------------------------


def set_realisations(
    db: Session, project: Any, actor: User, connection_id: uuid.UUID, version: int, outer_ids: Sequence[uuid.UUID],
) -> ArchitectureConnection:
    """Makes the connections `connection_id` realises exactly `outer_ids`. The caller commits.

    Args:
        db: Session.
        project: The project (both connections must be its own).
        actor: Who changes it (audited).
        connection_id: The inner connection.
        version: The connection's `version` the editor was looking at (the optimistic lock).
        outer_ids: The outer connections it realises; duplicates are ignored.

    Returns:
        The connection; its `version` advances only when the set changed.

    Raises:
        RuleError: 404 for an unknown connection, 409 on a stale version, 400 when an outer connection is not the
            project's, is archived, is the connection itself, is not realisable (the ends do not lie inside one of its
            ends) or would form a cycle.
    """
    connection = get_connection(db, project.id, connection_id, lock=True)
    if connection.version != version:
        raise RuleError("This connection was changed by someone else; reload it.", 409)
    wanted = list(dict.fromkeys(outer_ids))
    if len(wanted) > MAX_REALISATIONS:
        raise RuleError(f"A connection can realise at most {MAX_REALISATIONS} connections.", 400)
    current = {
        r.outer_connection_id: r for r in db.scalars(
            select(ArchitectureConnectionRealisation).where(ArchitectureConnectionRealisation.inner_connection_id == connection.id)
        )
    }
    added = [i for i in wanted if i not in current]
    outers = {
        c.id: c for c in db.scalars(select(ArchitectureConnection).where(
            ArchitectureConnection.id.in_(added), ArchitectureConnection.project_id == project.id,
        ))
    } if added else {}
    if connection.id in added or set(added) - set(outers) or any(outers[i].is_archived for i in added):
        raise RuleError("A connection can realise only another open connection of this project.", 400)
    if added:
        ends = {e for c in (connection, *outers.values()) for e in (c.source_element_id, c.target_element_id)}
        parents = ancestor_parents(db, ends)
        if not all(realises_rule_holds(parents, connection, outers[i]) for i in added):
            raise RuleError(
                "A connection can realise another only when it lies inside the interface the other declares: "
                "both ends inside one end of it, or each end inside a different end.", 400,
            )
        edges: dict[uuid.UUID, set[uuid.UUID]] = {}
        for row in project_realisations(db, project.id):
            edges.setdefault(row.inner_connection_id, set()).add(row.outer_connection_id)
        if any(reaches(edges, i, connection.id) for i in added):
            raise RuleError("A connection cannot realise a connection that realises it.", 400)
    removed = [i for i in current if i not in wanted]
    if not added and not removed:
        return connection
    for outer_id in removed:
        db.delete(current[outer_id])
    for outer_id in added:
        db.add(ArchitectureConnectionRealisation(inner_connection_id=connection.id, outer_connection_id=outer_id))
    connection.version += 1
    db.flush()
    _audit_connection(
        db, connection.id, "updated", actor, project.id, fields=["realisations"], realisations_added=len(added),
        realisations_removed=len(removed),
    )
    return connection


# --- Boundary boxes ---------------------------------------------------------


def boundaries_of(db: Session, diagram_id: uuid.UUID) -> list[ArchitectureDiagramBoundary]:
    """The diagram's boundary boxes in the order they were made."""
    return list(db.scalars(
        select(ArchitectureDiagramBoundary).where(ArchitectureDiagramBoundary.diagram_id == diagram_id)
        .order_by(ArchitectureDiagramBoundary.created_at, ArchitectureDiagramBoundary.id)
    ))


def check_boundaries(
    db: Session, project_id: uuid.UUID, scope_id: uuid.UUID | None, wanted: Sequence[BoundaryIn],
    stored: Mapping[uuid.UUID, ArchitectureDiagramBoundary],
) -> None:
    """Checks the boxes of a layout save: each outer connection once, and each *new* box an open connection of the
    project that is outer for the diagram's scope. A box already stored is kept whatever the model now says.

    Raises:
        RuleError: 400 for a repeated connection, a box on a diagram with no scope, or a new box that is not for an
            open outer connection of the project.
    """
    ids = [b.connection_id for b in wanted]
    if len(set(ids)) != len(ids):
        raise RuleError("An outer connection can be drawn once on a diagram.", 400)
    new = [i for i in ids if i not in stored]
    if not new:
        return
    if scope_id is None:
        raise RuleError("Boundary boxes belong to a diagram of the inside of an element.", 400)
    rows = list(db.scalars(select(ArchitectureConnection).where(
        ArchitectureConnection.id.in_(new), ArchitectureConnection.project_id == project_id,
        ArchitectureConnection.is_archived.is_(False),
    )))
    if len(rows) != len(set(new)) or set(outer_sides(db, scope_id, rows)) != {c.id for c in rows}:
        raise RuleError("A boundary box must stand for an open connection that crosses the boundary of the diagram's element.", 400)


def sync_boundaries(db: Session, diagram_id: uuid.UUID, wanted: Sequence[BoundaryIn] | None) -> int:
    """Makes the stored boxes match `wanted` (`None` keeps them). Returns how many rows were added, removed or moved."""
    if wanted is None:
        return 0
    changed = 0
    stored = {b.connection_id: b for b in boundaries_of(db, diagram_id)}
    given = {b.connection_id: b for b in wanted}
    for connection_id, row in stored.items():
        box = given.get(connection_id)
        if box is None:
            db.delete(row)
            changed += 1
        elif (row.x, row.y, row.width, row.height) != (box.x, box.y, box.width, box.height):
            row.x, row.y, row.width, row.height = box.x, box.y, box.width, box.height
            changed += 1
    for connection_id, box in given.items():
        if connection_id not in stored:
            db.add(ArchitectureDiagramBoundary(
                diagram_id=diagram_id, connection_id=connection_id, x=box.x, y=box.y, width=box.width, height=box.height,
            ))
            changed += 1
    return changed


def clear_boundaries(db: Session, diagram_id: uuid.UUID) -> int:
    """Removes every box of a diagram (its scope changed, so the outer connections are different). Returns the count."""
    result = db.execute(delete(ArchitectureDiagramBoundary).where(ArchitectureDiagramBoundary.diagram_id == diagram_id))
    return int(result.rowcount or 0)
