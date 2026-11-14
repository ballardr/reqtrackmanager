"""
Module: modules.architecture.search

The `ArtefactSearchProvider`s for the `architecture_element`, `architecture_connection` and
`architecture_diagram`, `architecture_state_machine_diagram` and `architecture_state` artefact types, so the global search
finds them by code, name, tags and descriptive text.

Responsibilities:
- Declare the columns the search reads and the opt-in free-text fields it may match.

Design decisions:
- Opt-in fields: the description (a diagram's purpose, under the shared `description` key), an element's port
  names and a connection's protocol. No record holds personal data or a Restricted-classified value. Comments
  (the shared record comments, pinned or not) are matched only when a person asks for them. A diagram's notes are
  not searched (free text on a drawing, not a described property).
- A connection with no name is titled by its code, so a result is never blank.
- An element may be organisation-owned (`organization_owned`): the search finds it only through a project the
  owning module's `get_many_in_project` rule (`summaries`, collection grants to the project) allows. A
  project-owned element is found through the projects the person can open; one shared from a project the person
  cannot open is reached through the shared list and the pickers, not the global search.

Dependencies: this module's models and labels; `modules.registry` (provider types).
"""

from __future__ import annotations

from sqlalchemy import case, exists, func, select

from app.models.record_comment import RecordComment
from app.modules.architecture.labels import RECORD_STATUS_LABEL
from app.modules.architecture.models import (
    ArchitectureConnection,
    ArchitectureDiagram,
    ArchitectureElement,
    ArchitecturePort,
    ArchitectureState,
    ArchitectureStateMachineDiagram,
)
from app.modules.architecture.service import (
    CONNECTION_ARTEFACT_TYPE,
    DIAGRAM_ARTEFACT_TYPE,
    ELEMENT_ARTEFACT_TYPE,
    STATE_ARTEFACT_TYPE,
    STATE_MACHINE_ARTEFACT_TYPE,
)
from app.modules.registry import ArtefactSearchProvider, SearchColumns, SearchComments, SearchField


def _comments(artefact_type: str) -> SearchComments:
    """The shared record comments of one architecture type, matched only when a person asks for comments."""
    return SearchComments(
        RecordComment, RecordComment.record_id, RecordComment.body, RecordComment.created_at,
        where=(RecordComment.artefact_type == artefact_type,),
    )


#: A state machine diagram (and so its states) is found by the global search only when it describes an element of its own
#: project: the search has no person, so it cannot apply the sharing rules that decide whether another owner's element is
#: readable, and a diagram of an element the person cannot read must not be disclosed. One of a shared element is reached
#: through the project's lists and the link finder, which do apply them.
_OWN_ELEMENT = exists().where(
    ArchitectureElement.id == ArchitectureStateMachineDiagram.element_id,
    ArchitectureElement.project_id == ArchitectureStateMachineDiagram.project_id,
)

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
            SearchField("display_note", "Display note", ArchitectureElement.display_note),
            SearchField("ports", "Port names", select(func.string_agg(ArchitecturePort.name, " ")).where(
                ArchitecturePort.element_id == ArchitectureElement.id,
            ).scalar_subquery()),
        ),
        status_labels=RECORD_STATUS_LABEL,
        organization_owned=True,
        comments=_comments(ELEMENT_ARTEFACT_TYPE),
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
        comments=_comments(CONNECTION_ARTEFACT_TYPE),
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
        comments=_comments(DIAGRAM_ARTEFACT_TYPE),
    ),
    STATE_MACHINE_ARTEFACT_TYPE: ArtefactSearchProvider(
        from_clause=ArchitectureStateMachineDiagram.__table__,
        columns=SearchColumns(
            id=ArchitectureStateMachineDiagram.id, project_id=ArchitectureStateMachineDiagram.project_id,
            code=ArchitectureStateMachineDiagram.unique_code, title=ArchitectureStateMachineDiagram.name,
            status=ArchitectureStateMachineDiagram.status, is_archived=ArchitectureStateMachineDiagram.is_archived,
            updated_at=ArchitectureStateMachineDiagram.updated_at, version=ArchitectureStateMachineDiagram.version,
        ),
        fields=(SearchField("description", "Description", ArchitectureStateMachineDiagram.description),),
        where=(_OWN_ELEMENT,),
        status_labels=RECORD_STATUS_LABEL,
        comments=_comments(STATE_MACHINE_ARTEFACT_TYPE),
    ),
    # A state has no status or archive flag of its own: it follows its diagram, which a subquery reads, and a result opens
    # the diagram with the state selected.
    STATE_ARTEFACT_TYPE: ArtefactSearchProvider(
        from_clause=ArchitectureState.__table__.join(
            ArchitectureStateMachineDiagram.__table__,
            ArchitectureStateMachineDiagram.id == ArchitectureState.state_machine_diagram_id,
        ),
        columns=SearchColumns(
            id=ArchitectureState.id, project_id=ArchitectureState.project_id, code=ArchitectureState.unique_code,
            title=ArchitectureState.name, status=ArchitectureStateMachineDiagram.status,
            is_archived=ArchitectureStateMachineDiagram.is_archived, updated_at=ArchitectureState.updated_at,
            owner_id=ArchitectureState.state_machine_diagram_id,
        ),
        fields=(
            SearchField("description", "Description", ArchitectureState.description),
            SearchField("entry_action", "Entry action", ArchitectureState.entry_action),
            SearchField("exit_action", "Exit action", ArchitectureState.exit_action),
            SearchField("activity", "Activity", ArchitectureState.activity),
        ),
        where=(_OWN_ELEMENT,),
        status_labels=RECORD_STATUS_LABEL,
        open_owner_type=STATE_MACHINE_ARTEFACT_TYPE,
    ),
}
