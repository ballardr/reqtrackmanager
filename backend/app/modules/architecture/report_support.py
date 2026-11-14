"""
Module: modules.architecture.report_support

Helpers the module's reports share, so each names an element, a connection end and a person the same way.

Responsibilities:
- `element_text`: an element as a report names it, or "Shared element" for one the reported project does not own.
- `project_elements` / `live_connections`: the reported project's elements and its connections still in force.
- `chain_of`: the parent chain of an element (cycle-safe, depth-capped).
- `viewer_for`: the `Viewer` a report reads as (the person it runs for, else the project).

Design decisions:
- **Only elements of the reported project are named.** An end owned by another project or the organisation shows as
  "Shared element" with no code or name, so a report discloses nothing the reader's project access does not cover.
- Archived records and retired or rejected connections are left out of every report.

Dependencies: this module's models, labels and visibility; `app.services.report_framework`.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.project import Project
from app.models.user import User
from app.modules.architecture.labels import INACTIVE_STATUSES
from app.modules.architecture.models import ArchitectureConnection, ArchitectureElement
from app.modules.architecture.visibility import Viewer
from app.services.report_framework import ReportContext

SHARED = "Shared element"
_DEPTH_CAP = 64


def element_text(req: ReportContext, project_id: uuid.UUID, elements: dict[uuid.UUID, ArchitectureElement], element_id: uuid.UUID) -> str:
    """An element as the report names it: its code and name, or "Shared element" for one the project does not own.

    Args:
        req: The report request (applies the project-code rule).
        project_id: The reported project.
        elements: The project's elements by id (`project_elements`).
        element_id: The element to name.

    Returns:
        `"ELM-003 Encoder"` (code qualified as the report's rule says), or `"Shared element"`.
    """
    element = elements.get(element_id)
    return f"{req.code(element.unique_code, project_id)} {element.name}".strip() if element is not None else SHARED


def project_elements(db: Session, project_id: uuid.UUID, *, include_archived: bool = False) -> dict[uuid.UUID, ArchitectureElement]:
    """The project's own elements by id (archived ones only when asked)."""
    query = select(ArchitectureElement).where(ArchitectureElement.project_id == project_id)
    if not include_archived:
        query = query.where(ArchitectureElement.is_archived.is_(False))
    return {e.id: e for e in db.scalars(query.order_by(ArchitectureElement.unique_code))}


def live_connections(db: Session, project_id: uuid.UUID) -> list[ArchitectureConnection]:
    """The project's connections that are not archived, retired or rejected, in code order."""
    return list(db.scalars(
        select(ArchitectureConnection).where(
            ArchitectureConnection.project_id == project_id, ArchitectureConnection.is_archived.is_(False),
            ArchitectureConnection.status.not_in(INACTIVE_STATUSES),
        ).order_by(ArchitectureConnection.unique_code)
    ))


def chain_of(parents: dict[uuid.UUID, uuid.UUID | None], element_id: uuid.UUID) -> list[uuid.UUID]:
    """The element and its ancestors, nearest first (cycle-safe)."""
    seen: list[uuid.UUID] = []
    current: uuid.UUID | None = element_id
    while current is not None and current not in seen and len(seen) < _DEPTH_CAP:
        seen.append(current)
        current = parents.get(current)
    return seen


def find_element(elements: dict[uuid.UUID, ArchitectureElement], wanted: str) -> ArchitectureElement | None:
    """The element whose code or name equals `wanted` (case-insensitive), or `None`."""
    key = wanted.strip().casefold()
    return next((e for e in elements.values() if key in (e.unique_code.casefold(), e.name.casefold())), None) if key else None


def viewer_for(db: Session, req: ReportContext, project: Project) -> Viewer:
    """Who a report reads as: the person it runs for when known, else the project alone."""
    user = db.get(User, req.viewer_id) if req.viewer_id is not None else None
    return Viewer.of_user(user, project) if user is not None else Viewer.of_project(project.id, project.organization_id)
