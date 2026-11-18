"""
Module: modules.architecture.realisations

The "realises" link between two connections, without any rule that needs the record layer: reading the rows in bulk,
testing whether a pair satisfies the rule, and pruning rows an edit made invalid. `boundaries.set_realisations` is the
validated write; `records` calls the pruning when a connection's end or an element's parent changes, so an edit cannot
leave a stale row.

Design decisions:
- **A pair is valid when the inner connection lies inside the interface the outer one declares:** both its ends inside
  one end element of the outer connection (that element or a descendant), or each end inside a different end of it (the
  interface refined between parts of its two ends). Ports play no part: a connection that ends at the element through a
  port still ends at the element.
- **Kept separate from `boundaries`** because `records` must call the pruning while `boundaries` itself needs
  `records` (rule errors, audit); one leaf module avoids the import cycle.

Dependencies: `models`, `visibility` (the ancestor walk).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.architecture.models import ArchitectureConnection, ArchitectureConnectionRealisation
from app.modules.architecture.visibility import ancestor_parents, descendant_ids


def realisations_of(db: Session, connection_ids: Iterable[uuid.UUID]) -> list[ArchitectureConnectionRealisation]:
    """The realisation rows that name any of the connections, as inner or outer, in one statement."""
    wanted = set(connection_ids)
    if not wanted:
        return []
    return list(db.scalars(
        select(ArchitectureConnectionRealisation).where(
            ArchitectureConnectionRealisation.inner_connection_id.in_(wanted)
            | ArchitectureConnectionRealisation.outer_connection_id.in_(wanted)
        ).order_by(ArchitectureConnectionRealisation.created_at, ArchitectureConnectionRealisation.id)
    ))


def project_realisations(db: Session, project_id: uuid.UUID) -> list[ArchitectureConnectionRealisation]:
    """Every realisation of the project's connections (both ends are the project's own), in one statement."""
    return list(db.scalars(
        select(ArchitectureConnectionRealisation)
        .join(ArchitectureConnection, ArchitectureConnection.id == ArchitectureConnectionRealisation.inner_connection_id)
        .where(ArchitectureConnection.project_id == project_id)
        .order_by(ArchitectureConnectionRealisation.created_at, ArchitectureConnectionRealisation.id)
    ))


def realisation_refs(
    db: Session, connections: Sequence[ArchitectureConnection],
) -> dict[uuid.UUID, tuple[list[uuid.UUID], list[uuid.UUID]]]:
    """`{connection id: (the outer connections it realises, the inner connections that realise it)}` in one statement."""
    found: dict[uuid.UUID, tuple[list[uuid.UUID], list[uuid.UUID]]] = {c.id: ([], []) for c in connections}
    for row in realisations_of(db, found):
        if row.inner_connection_id in found:
            found[row.inner_connection_id][0].append(row.outer_connection_id)
        if row.outer_connection_id in found:
            found[row.outer_connection_id][1].append(row.inner_connection_id)
    return found


def chain(parents: Mapping[uuid.UUID, uuid.UUID | None], element_id: uuid.UUID) -> set[uuid.UUID]:
    """The element and its ancestors (cycle-safe; the depth cap of an element tree is far below the bound)."""
    seen: set[uuid.UUID] = set()
    current: uuid.UUID | None = element_id
    while current is not None and current not in seen and len(seen) < 64:
        seen.add(current)
        current = parents.get(current)
    return seen


def realises_rule_holds(
    parents: Mapping[uuid.UUID, uuid.UUID | None], inner: ArchitectureConnection, outer: ArchitectureConnection,
) -> bool:
    """Whether `inner` may realise `outer`: it lies inside the interface `outer` declares.

    Either both ends of `inner` lie inside one end element of `outer` (the element itself or a descendant: the lower
    layer's own part of the interface), or each end of `inner` lies inside a different end of `outer`, source to source
    and target to target or crosswise (the interface refined between parts of its two ends).
    """
    in_source = {end: end in chain(parents, inner.source_element_id) for end in (outer.source_element_id, outer.target_element_id)}
    in_target = {end: end in chain(parents, inner.target_element_id) for end in (outer.source_element_id, outer.target_element_id)}
    if any(in_source[end] and in_target[end] for end in in_source):
        return True
    a, b = outer.source_element_id, outer.target_element_id
    return (in_source[a] and in_target[b]) or (in_source[b] and in_target[a])


def reaches(edges: Mapping[uuid.UUID, set[uuid.UUID]], start: uuid.UUID, goal: uuid.UUID) -> bool:
    """Whether following 'realises' edges from `start` reaches `goal`."""
    stack, seen = [start], {start}
    while stack:
        node = stack.pop()
        if node == goal:
            return True
        for nxt in edges.get(node, ()):
            if nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
    return False


def _prune_rows(db: Session, rows: Sequence[ArchitectureConnectionRealisation]) -> int:
    """Deletes the given rows whose pair of connections no longer satisfies the rule. Returns how many."""
    if not rows:
        return 0
    ids = {i for r in rows for i in (r.inner_connection_id, r.outer_connection_id)}
    by_id = {c.id: c for c in db.scalars(select(ArchitectureConnection).where(ArchitectureConnection.id.in_(ids)))}
    parents = ancestor_parents(db, {e for c in by_id.values() for e in (c.source_element_id, c.target_element_id)})
    removed = 0
    for row in rows:
        inner, outer = by_id.get(row.inner_connection_id), by_id.get(row.outer_connection_id)
        if inner is None or outer is None or not realises_rule_holds(parents, inner, outer):
            db.delete(row)
            removed += 1
    if removed:
        db.flush()
    return removed


def prune_realisations(db: Session, connection: ArchitectureConnection) -> int:
    """Deletes the realisations naming `connection` that its ends no longer satisfy (after an end was edited).

    Returns:
        How many rows were removed.
    """
    return _prune_rows(db, realisations_of(db, [connection.id]))


def prune_for_elements(db: Session, element_ids: Iterable[uuid.UUID]) -> int:
    """Deletes the realisations that name a connection ending at one of the elements or a descendant, when the tree no
    longer satisfies the rule (after an element moved). Returns how many rows were removed."""
    subtree = descendant_ids(db, element_ids)
    if not subtree:
        return 0
    touching = set(db.scalars(select(ArchitectureConnection.id).where(
        ArchitectureConnection.source_element_id.in_(subtree) | ArchitectureConnection.target_element_id.in_(subtree)
    )))
    return _prune_rows(db, realisations_of(db, touching))
