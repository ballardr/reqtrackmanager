"""
Module: modules.architecture.summaries

The `ArtefactSummaryProvider`s for the `architecture_element`, `architecture_connection` and
`architecture_diagram` artefact types, so core (the link graph, the "Add a link" finder) and other modules can label, status-badge
and visibility-check an element or a connection without importing its models.

Responsibilities:
- Build an `ArtefactSummary` (`ELM-001 name`, `CON-001 name (ELM-001 → ELM-002)`, status, archived
  flag) with a `status` facet for the finder, and offer one-query batch lookups for a viewing project.

Design decisions:
- A project sees its own records here and the elements other owners share with it (`visibility.Viewer.of_project`:
  collection grants to the project or an ancestor with descendants). The hooks have no person, so a grant to a
  group, or access through another project the person can open, is not applied here; that is only ever less
  than the person's own view. An organisation-owned element carries no project and its organisation, and no
  `list_for_organization` is offered: core resolves an organisation-qualified code for any member of the
  organisation, which would show an element nobody shared with them.
- A connection with no name is labelled by its code and its ends. A diagram is the project's own record
  (`DGM-001 name`) and is never shared, so its provider reads the project's rows only.

Dependencies: this module's models and labels; `modules.registry` for the summary dataclasses;
`services.summary_facets`.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, aliased

from app.models.project import Project
from app.modules.architecture.labels import INACTIVE_STATUSES, RECORD_STATUS_LABEL
from app.modules.architecture.models import ArchitectureConnection, ArchitectureDiagram, ArchitectureElement
from app.modules.architecture.visibility import Viewer, granted_element_ids, visible_element_ids
from app.modules.registry import ArtefactSummary, ArtefactSummaryProvider, BrowseLevel
from app.services.summary_facets import status_facet

BROWSE_LEVELS = (BrowseLevel("status", "Status"),)


def _facets(status: str) -> dict[str, Any]:
    """The `status` facet a summary carries for the scoped finder."""
    return {"status": status_facet(status, RECORD_STATUS_LABEL)}


def _element_query(*conditions: Any):
    return select(ArchitectureElement).where(*conditions)


def _element_summaries(elements: Sequence[ArchitectureElement]) -> list[ArtefactSummary]:
    return [
        ArtefactSummary(
            id=e.id, project_id=e.project_id, organization_id=e.organization_id, label=f"{e.unique_code} {e.name}",
            status=e.status, is_archived=e.is_archived, facets=_facets(e.status),
        )
        for e in elements
    ]


def _get_element(db: Session, element_id: UUID) -> ArtefactSummary | None:
    element = db.scalar(_element_query(ArchitectureElement.id == element_id))
    return None if element is None else _element_summaries([element])[0]


def _viewer(db: Session, project_id: UUID) -> Viewer:
    """The project as a viewer with no person (see the module docstring)."""
    organization_id = db.scalar(select(Project.organization_id).where(Project.id == project_id))
    assert organization_id is not None
    return Viewer.of_project(project_id, organization_id)


def _list_elements(db: Session, project_id: UUID) -> list[ArtefactSummary]:
    """The project's own open-or-draft elements and the unarchived, unretired elements shared with it."""
    shared = granted_element_ids(db, _viewer(db, project_id))
    rows = db.scalars(_element_query(
        ArchitectureElement.is_archived.is_(False),
        (ArchitectureElement.project_id == project_id)
        | (ArchitectureElement.id.in_(shared) & ArchitectureElement.status.not_in(INACTIVE_STATUSES)),
    )).all()
    return sorted(_element_summaries(rows), key=lambda s: s.label)


def _get_many_elements(db: Session, project_id: UUID, ids: Sequence[UUID]) -> list[ArtefactSummary]:
    visible = visible_element_ids(db, _viewer(db, project_id), ids)
    if not visible:
        return []
    return _element_summaries(db.scalars(_element_query(ArchitectureElement.id.in_(visible))).all())


ELEMENT_SUMMARY_PROVIDER = ArtefactSummaryProvider(
    get=_get_element, list_for_project=_list_elements, get_many_in_project=_get_many_elements,
    browse_levels=BROWSE_LEVELS,
)


def _connection_query(*conditions: Any):
    source, target = aliased(ArchitectureElement), aliased(ArchitectureElement)
    return select(ArchitectureConnection, source.unique_code, target.unique_code).join(
        source, source.id == ArchitectureConnection.source_element_id,
    ).join(target, target.id == ArchitectureConnection.target_element_id).where(*conditions)


def _connection_summaries(rows: Sequence[Any]) -> list[ArtefactSummary]:
    return [
        ArtefactSummary(
            id=c.id, project_id=c.project_id,
            label=f"{c.unique_code} {c.name + ' ' if c.name else ''}({source} → {target})",
            status=c.status, is_archived=c.is_archived, facets=_facets(c.status),
        )
        for c, source, target in rows
    ]


def _get_connection(db: Session, connection_id: UUID) -> ArtefactSummary | None:
    row = db.execute(_connection_query(ArchitectureConnection.id == connection_id)).first()
    return None if row is None else _connection_summaries([tuple(row)])[0]


def _list_connections(db: Session, project_id: UUID) -> list[ArtefactSummary]:
    rows = db.execute(_connection_query(
        ArchitectureConnection.project_id == project_id, ArchitectureConnection.is_archived.is_(False),
    )).all()
    return sorted(_connection_summaries([tuple(r) for r in rows]), key=lambda s: s.label)


def _get_many_connections(db: Session, project_id: UUID, ids: Sequence[UUID]) -> list[ArtefactSummary]:
    rows = db.execute(_connection_query(
        ArchitectureConnection.id.in_(ids), ArchitectureConnection.project_id == project_id,
    )).all()
    return _connection_summaries([tuple(r) for r in rows])


CONNECTION_SUMMARY_PROVIDER = ArtefactSummaryProvider(
    get=_get_connection, list_for_project=_list_connections, get_many_in_project=_get_many_connections,
    browse_levels=BROWSE_LEVELS,
)


def _diagram_summaries(rows: Sequence[ArchitectureDiagram]) -> list[ArtefactSummary]:
    return [
        ArtefactSummary(
            id=d.id, project_id=d.project_id, label=f"{d.unique_code} {d.name}", status=d.status, is_archived=d.is_archived,
            facets=_facets(d.status),
        )
        for d in rows
    ]


def _get_diagram(db: Session, diagram_id: UUID) -> ArtefactSummary | None:
    row = db.get(ArchitectureDiagram, diagram_id)
    return None if row is None else _diagram_summaries([row])[0]


def _list_diagrams(db: Session, project_id: UUID) -> list[ArtefactSummary]:
    rows = db.scalars(select(ArchitectureDiagram).where(
        ArchitectureDiagram.project_id == project_id, ArchitectureDiagram.is_archived.is_(False),
    )).all()
    return sorted(_diagram_summaries(rows), key=lambda s: s.label)


def _get_many_diagrams(db: Session, project_id: UUID, ids: Sequence[UUID]) -> list[ArtefactSummary]:
    return _diagram_summaries(db.scalars(select(ArchitectureDiagram).where(
        ArchitectureDiagram.id.in_(ids), ArchitectureDiagram.project_id == project_id,
    )).all())


DIAGRAM_SUMMARY_PROVIDER = ArtefactSummaryProvider(
    get=_get_diagram, list_for_project=_list_diagrams, get_many_in_project=_get_many_diagrams, browse_levels=BROWSE_LEVELS,
)
