"""
Module: modules.architecture.connection_tree

The rules of the connection type tree: a type may sit under several parents, to any depth, and a group is itself a
usable type.

Responsibilities:
- `check_tree` refuses an edit that makes a cycle or a chain deeper than `MAX_TYPE_DEPTH`.
- `descendant_map` / `closure_of` expand a type to itself and everything beneath it, so a filter by a group finds
  the connections typed with any of its members.

Design decisions:
- Pure functions over a `{child: {parents}}` mapping for validation, so the rule is tested without a database.
- Expansion walks the whole link table level by level (one statement per level, at most `MAX_TYPE_DEPTH`),
  whichever tier owns a type, because a record may be typed by any row its project could use.

Dependencies: this module's models.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.architecture.models import ArchitectureConnectionTypeParent

#: The longest chain of nested types (a root counts as one level).
MAX_TYPE_DEPTH = 12


def check_tree(links: Mapping[uuid.UUID, set[uuid.UUID]], child_id: uuid.UUID, parent_ids: Iterable[uuid.UUID]) -> None:
    """Checks that giving `child_id` exactly `parent_ids` keeps the tree acyclic and within `MAX_TYPE_DEPTH`.

    Args:
        links: `{type id: ids of its parents}` for every type the edit can reach; the child's own entry is replaced.
        child_id: The type being edited (a type not yet created passes a fresh id).
        parent_ids: The parents it is to have.

    Raises:
        ValueError: If a parent is the type itself or beneath it (a cycle), or the chain would be too deep.
    """
    wanted = set(parent_ids)
    if child_id in wanted:
        raise ValueError("A connection type cannot be its own parent.")
    proposed = {**links, child_id: wanted}
    children: dict[uuid.UUID, set[uuid.UUID]] = {}
    for node, parents in proposed.items():
        for parent in parents:
            children.setdefault(parent, set()).add(node)

    def height(node: uuid.UUID, edges: Mapping[uuid.UUID, set[uuid.UUID]], path: frozenset[uuid.UUID]) -> int:
        """Levels from `node` along `edges`, counting `node`; a node met twice on one path is a cycle."""
        if node in path:
            raise ValueError("A connection type cannot sit beneath itself.")
        if len(path) >= MAX_TYPE_DEPTH:
            raise ValueError(f"Connection types can be nested at most {MAX_TYPE_DEPTH} levels deep.")
        return 1 + max((height(n, edges, path | {node}) for n in edges.get(node, ())), default=0)

    above = height(child_id, proposed, frozenset())
    below = height(child_id, children, frozenset())
    if above + below - 1 > MAX_TYPE_DEPTH:
        raise ValueError(f"Connection types can be nested at most {MAX_TYPE_DEPTH} levels deep.")


def descendant_map(db: Session, type_ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, set[uuid.UUID]]:
    """Each given type with everything beneath it (the type itself included), in one statement per level.

    Args:
        db: Session.
        type_ids: The types to expand.

    Returns:
        `{type id: the type and its descendants}`; an id with no children maps to just itself.
    """
    wanted = set(type_ids)
    children: dict[uuid.UUID, set[uuid.UUID]] = {}
    frontier, seen = set(wanted), set(wanted)
    for _ in range(MAX_TYPE_DEPTH):
        if not frontier:
            break
        found = db.execute(select(
            ArchitectureConnectionTypeParent.parent_id, ArchitectureConnectionTypeParent.child_id,
        ).where(ArchitectureConnectionTypeParent.parent_id.in_(frontier))).tuples().all()
        frontier = set()
        for parent, child in found:
            children.setdefault(parent, set()).add(child)
            if child not in seen:
                seen.add(child)
                frontier.add(child)

    def below(root: uuid.UUID) -> set[uuid.UUID]:
        out, stack = {root}, [root]
        while stack:
            for child in children.get(stack.pop(), ()):
                if child not in out:
                    out.add(child)
                    stack.append(child)
        return out

    return {root: below(root) for root in wanted}


def closure_of(db: Session, type_ids: Iterable[uuid.UUID]) -> set[uuid.UUID]:
    """The given types and everything beneath them, as one set."""
    return set().union(*descendant_map(db, type_ids).values())
