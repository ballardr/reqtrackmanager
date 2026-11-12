"""
Module: modules.architecture.search

The `ArtefactSearchProvider`s for the `architecture_element` and `architecture_connection` artefact
types, so the global search finds them by code, name, tags and descriptive text.

Responsibilities:
- Declare the columns the search reads and the opt-in free-text fields it may match.

Design decisions:
- Opt-in fields: the description, an element's port names and a connection's protocol. Neither
  record holds personal data, a Restricted-classified value or comments.
- A connection with no name is titled by its code, so a result is never blank.

Dependencies: this module's models and labels; `modules.registry` (provider types).
"""

from __future__ import annotations

from sqlalchemy import case, func, select

from app.modules.architecture.labels import RECORD_STATUS_LABEL
from app.modules.architecture.models import ArchitectureConnection, ArchitectureElement, ArchitecturePort
from app.modules.architecture.service import CONNECTION_ARTEFACT_TYPE, ELEMENT_ARTEFACT_TYPE
from app.modules.registry import ArtefactSearchProvider, SearchColumns, SearchField

SEARCH_PROVIDERS: dict[str, ArtefactSearchProvider] = {
    ELEMENT_ARTEFACT_TYPE: ArtefactSearchProvider(
        from_clause=ArchitectureElement.__table__,
        columns=SearchColumns(
            id=ArchitectureElement.id, project_id=ArchitectureElement.project_id, code=ArchitectureElement.unique_code,
            title=ArchitectureElement.name, status=ArchitectureElement.status,
            is_archived=ArchitectureElement.is_archived, updated_at=ArchitectureElement.updated_at,
            version=ArchitectureElement.version,
        ),
        fields=(
            SearchField("description", "Description", ArchitectureElement.description),
            SearchField("ports", "Port names", select(func.string_agg(ArchitecturePort.name, " ")).where(
                ArchitecturePort.element_id == ArchitectureElement.id,
            ).scalar_subquery()),
        ),
        status_labels=RECORD_STATUS_LABEL,
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
}
