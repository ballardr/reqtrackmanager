"""
Module: services.report_layout_scope

Which report layouts a project can see, and hiding or restoring the inherited ones.

Responsibilities:
- `resolve_project_layouts`: the layouts a project can reach, each with where it comes from.
- `hide_layout` / `restore_layouts`: a project hides an inherited layout and brings it back.
- `list_org_layouts`: an organisation's own layouts.

Design decisions:
- **Visibility is additive.** A project sees its own layouts, its ancestors' (nearest first) and the
  organisation's, de-duplicated by name (case-insensitively) with the nearest owner winning. The Action
  Types rule ("own rows, else the nearest ancestor's") would hide every inherited layout the moment a
  project made one of its own, so it is not used here. A name that a nearer layout shadows is not
  listed and cannot be hidden separately.
- **Hiding is a tombstone** (`ProjectDefinitionSuppression`, kind `report_layout`), per project and not
  inherited downwards, exactly as the other organisation defaults. Only an inherited layout can be
  hidden; a project removes its own by deleting it. A hidden layout keeps its name, so it does not let a
  farther layout of the same name show through.
- Platform starter layouts are added to this resolution when they exist; they will be a further,
  read-only tier below the organisation.

Dependencies: `models.report_layout`, `services.project_hierarchy`, `services.definition_suppression`.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.project import Project
from app.models.report_layout import ReportLayout
from app.services import definition_suppression
from app.services.audit import log_event
from app.services.project_hierarchy import get_project_chain_ids

LAYOUT_KIND = "report_layout"
"""The `ProjectDefinitionSuppression.definition_kind` of a hidden report layout."""

definition_suppression.register_definition_kind(LAYOUT_KIND)

Origin = Literal["organization", "ancestor", "project"]


@dataclass(frozen=True)
class ScopedLayout:
    """A layout as one project sees it.

    Attributes:
        layout: The layout row.
        origin: `project` (its own), `ancestor` (a parent project's) or `organization`.
        hidden: Whether this project has hidden it (never true for its own).
    """

    layout: ReportLayout
    origin: Origin
    hidden: bool


def list_org_layouts(db: Session, organization_id: uuid.UUID) -> list[ReportLayout]:
    """The organisation-level layouts of `organization_id`, by name."""
    return list(db.scalars(
        select(ReportLayout)
        .where(ReportLayout.organization_id == organization_id, ReportLayout.project_id.is_(None))
        .order_by(ReportLayout.name)
    ).all())


def resolve_project_layouts(db: Session, project: Project) -> list[ScopedLayout]:
    """Every layout `project` can reach, nearest owner first, hidden ones flagged.

    Args:
        db: Active session.
        project: The project.

    Returns:
        The de-duplicated layouts: the project's own, then each ancestor's (nearest first), then the
        organisation's; within a tier by name. A farther layout whose name a nearer one already uses is
        left out.
    """
    chain = get_project_chain_ids(db, project.id)  # the project itself first, then its parent ... the root
    rows = list(db.scalars(
        select(ReportLayout).where(
            ReportLayout.organization_id == project.organization_id,
            (ReportLayout.project_id.in_(chain)) | (ReportLayout.project_id.is_(None)),
        )
    ).all())
    rank = {pid: i for i, pid in enumerate(chain)}
    rows.sort(key=lambda r: (rank.get(r.project_id, len(chain)) if r.project_id else len(chain), r.name.lower()))
    hidden_ids = definition_suppression.get_suppressed_ids(db, project.id, LAYOUT_KIND)
    seen: set[str] = set()
    out: list[ScopedLayout] = []
    for row in rows:
        key = row.name.strip().lower()
        if key in seen:
            continue
        seen.add(key)
        origin: Origin = "organization" if row.project_id is None else ("project" if row.project_id == project.id else "ancestor")
        out.append(ScopedLayout(row, origin, hidden=origin != "project" and row.id in hidden_ids))
    return out


def reachable_layout(db: Session, project: Project, layout_id: uuid.UUID) -> ScopedLayout | None:
    """`layout_id` as `project` sees it, or `None` when it is not reachable (another owner's, or shadowed)."""
    return next((s for s in resolve_project_layouts(db, project) if s.layout.id == layout_id), None)


def hide_layout(db: Session, project: Project, layout_id: uuid.UUID, *, actor_id: uuid.UUID | None) -> bool:
    """Hides an inherited layout in `project`. Idempotent.

    Raises:
        LookupError: The layout is not one the project inherits (unreachable, shadowed, or its own).
    """
    scoped = reachable_layout(db, project, layout_id)
    if scoped is None or scoped.origin == "project":
        raise LookupError("No such inherited layout.")
    created = definition_suppression.hide_definition(db, project.id, LAYOUT_KIND, layout_id)
    if created:
        log_event(
            db, entity_type="report_layout", entity_id=layout_id, action="hidden", actor_id=actor_id,
            organization_id=project.organization_id, project_id=project.id, detail={},
        )
    return created


def restore_layouts(
    db: Session, project: Project, layout_ids: set[uuid.UUID] | None, *, actor_id: uuid.UUID | None,
) -> set[uuid.UUID]:
    """Shows hidden layouts in `project` again.

    Args:
        layout_ids: The layouts to restore, or `None` for every hidden one.

    Returns:
        The ids restored.
    """
    restored = definition_suppression.restore_definitions(db, project.id, LAYOUT_KIND, layout_ids)
    for layout_id in sorted(restored, key=str):
        log_event(
            db, entity_type="report_layout", entity_id=layout_id, action="restored", actor_id=actor_id,
            organization_id=project.organization_id, project_id=project.id, detail={},
        )
    return restored


__all__ = [
    "LAYOUT_KIND", "Origin", "ScopedLayout", "hide_layout", "list_org_layouts", "reachable_layout",
    "resolve_project_layouts", "restore_layouts",
]
