"""
Module: services.ordering

Shared reordering logic for any `sort_order`-ordered sibling group.
Extracted from `routers.projects` (originally private to that module,
serving only `ProjectComponent`/`ProjectCategory` reordering) so the new
org-scoped and project-scoped definition tables introduced alongside
project statuses, requirement link types, and requirement actions
(`ProjectStatusDefinition`, `RequirementLinkTypeDefinition`,
`ActionTypeDefinition`) can reuse the exact same swap logic instead of each
router reimplementing it — this codebase's CLAUDE.md explicitly calls for
reusing existing helpers rather than reinventing them.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session


def move_ordered(db: Session, model, scope_conditions: list, item_id: UUID, direction: str):
    """Swaps `sort_order` between `item_id` and its neighbour (C-E-01/C-E-02).

    Shared by every `sort_order`-ordered sibling group in this codebase:
    components/categories within a project (`routers.projects`), and the
    three org-/project-scoped definition tables (project statuses, link
    types, action types) within their organisation/project. A no-op (not
    an error) if the item is already at the boundary in the requested
    direction.

    Args:
        db: Active database session.
        model: The SQLAlchemy model class being reordered.
        scope_conditions: SQLAlchemy filter expressions identifying the
            sibling group `item_id` is ordered within (e.g. same
            `project_id` for components, same `organization_id` for
            project statuses).
        item_id: The row being moved.
        direction: "up" or "down".

    Returns:
        The moved row, refreshed with its (possibly unchanged) sort_order.

    Raises:
        HTTPException: 404 if `item_id` isn't found among the scoped siblings.
    """
    items = db.scalars(select(model).where(*scope_conditions).order_by(model.sort_order)).all()
    idx = next((i for i, it in enumerate(items) if it.id == item_id), None)
    if idx is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Item not found.")
    swap_idx = idx - 1 if direction == "up" else idx + 1
    if 0 <= swap_idx < len(items):
        items[idx].sort_order, items[swap_idx].sort_order = items[swap_idx].sort_order, items[idx].sort_order
        db.commit()
    db.refresh(items[idx])
    return items[idx]
