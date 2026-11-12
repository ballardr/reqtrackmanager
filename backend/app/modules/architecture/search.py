"""
Module: modules.architecture.search

The `ArtefactSearchProvider`s for the `architecture_element`, `architecture_connection` and
`architecture_diagram` artefact types, so the global search finds them by code, name, tags and descriptive text.

Responsibilities:
- Declare the columns the search reads and the opt-in free-text fields it may match.

Design decisions:
- Opt-in fields: the description (a diagram's purpose, under the shared `description` key), an element's port
  names and a connection's protocol. No record holds personal data, a Restricted-classified value or comments.
  A diagram's notes are not searched (free text on a drawing, not a described property).
- A connection with no name is titled by its code, so a result is never blank.
- An element may be organisation-owned (`organization_owned`): the search finds it only through a project the
  owning module's `get_many_in_project` rule (`summaries`, collection grants to the project) allows. A
  project-owned element is found through the projects the person can open; one shared from a project the person
  cannot open is reached through the shared list and the pickers, not the global search.

Dependencies: this module's models and labels; `modules.registry` (provider types).
"""

from __future__ import annotations

from sqlalchemy import case, func, select

from app.modules.architecture.labels import RECORD_STATUS_LABEL
from app.modules.architecture.models import ArchitectureConnection, ArchitectureDiagram, ArchitectureElement, ArchitecturePort
from app.modules.architecture.service import CONNECTION_ARTEFACT_TYPE, DIAGRAM_ARTEFACT_TYPE, ELEMENT_ARTEFACT_TYPE
from app.modules.registry import ArtefactSearchProvider, SearchColumns, SearchField

SEARCH_PROVIDERS: dict[str, ArtefactSearchProvider] = {
    ELEMENT_ARTEFACT_TYPE: ArtefactSearchProvider(
        from_clause=ArchitectureElement.__table__,
        columns=SearchColumns(
            id=ArchitectureElement.id, project_id=ArchitectureElement.project_id, code=ArchitectureElement.unique_code,
            title=ArchitectureElement.name, status=ArchitectureElement.status,
            is_archived=ArchitectureElement.is_archived, updated_at=ArchitectureElement.updated_at,
            organization_id=ArchitectureElement.organization_id, version=ArchitectureElement.version,
        ),
        fields=(
            SearchField("description", "Description", ArchitectureElement.description),
            SearchField("ports", "Port names", select(func.string_agg(ArchitecturePort.name, " ")).where(
                ArchitecturePort.element_id == ArchitectureElement.id,
            ).scalar_subquery()),
        ),
        status_labels=RECORD_STATUS_LABEL,
        organization_owned=True,
    ),
    CONNECTION_ARTEFACT_TYPE: ArtefactSearchProvider(
        from_clause=ArchitectureConnection.__table__,
        columns=SearchColumns(
            id=ArchitectureConnection.id, project_id=ArchitectureConnection.project_id,
            code=ArchitectureConnection.unique_code,
            title=case((ArchitectureConnection.name != "", ArchitectureConnection.name), else_=ArchitectureConnection.unique_code),
            status=ArchitectureConnection.status, is_archived=ArchitectureConnection.is_archived,
            updated_at=ArchitectureConnection.updated_at, version=ArchitectureConnection.version,
        ),
        fields=(
            SearchField("description", "Description", ArchitectureConnection.description),
            SearchField("protocol", "Protocol", ArchitectureConnection.protocol),
        ),
        status_labels=RECORD_STATUS_LABEL,
    ),
    DIAGRAM_ARTEFACT_TYPE: ArtefactSearchProvider(
        from_clause=ArchitectureDiagram.__table__,
        columns=SearchColumns(
            id=ArchitectureDiagram.id, project_id=ArchitectureDiagram.project_id, code=ArchitectureDiagram.unique_code,
            title=ArchitectureDiagram.name, status=ArchitectureDiagram.status, is_archived=ArchitectureDiagram.is_archived,
            updated_at=ArchitectureDiagram.updated_at, version=ArchitectureDiagram.version,
        ),
        fields=(SearchField("description", "Description", ArchitectureDiagram.purpose),),
        status_labels=RECORD_STATUS_LABEL,
    ),
}
