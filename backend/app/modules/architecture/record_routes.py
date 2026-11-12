"""
Module: modules.architecture.record_routes

The project-scoped endpoints for elements, their ports and connections, added to the
module's project router by `add_record_routes`.

Responsibilities:
- Declare the routes and translate `records.RuleError` to its HTTP status.
- Apply the list filters (`filter_elements`, `filter_connections`) the lists and the
  record-table export share, so a file holds exactly what the page shows.

RBAC: reading needs project membership and the record type's sub-component to be
enabled; every change needs `_shared.require_architect` with the type's manage atom.
Every lookup is scoped to the project in the URL, so another project's ids look absent.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any, TypeVar

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.modules.architecture import records
from app.modules.architecture._shared import CONNECTION_MANAGE_PERMISSION, ELEMENT_MANAGE_PERMISSION, require_architect
from app.modules.architecture.enums import RecordStatus
from app.modules.architecture.models import ArchitectureConnection, ArchitectureElement
from app.modules.architecture.schemas import (
    ConnectionCreate,
    ConnectionOut,
    ConnectionUpdate,
    ElementCreate,
    ElementOut,
    ElementUpdate,
    PortCreate,
    PortOut,
    PortUpdate,
    StatusChange,
)
from app.modules.architecture.service import (
    ARCHITECTURE_MODULE_KEY,
    CONNECTION_ARTEFACT_TYPE,
    CONNECTION_SUBCOMPONENT_KEY,
    ELEMENT_ARTEFACT_TYPE,
    ELEMENT_SUBCOMPONENT_KEY,
)
from app.services.lookups import project_or_404
from app.services.project_scope import ProjectScope
from app.services.rbac import require_project_subcomponent_enabled
from app.services.tags import TagFilter

_T = TypeVar("_T")


def as_http(call: Callable[[], _T]) -> _T:
    """Runs `call`, answering a `records.RuleError` with the HTTP status it carries."""
    try:
        return call()
    except records.RuleError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc


def _matches(text: str | None, *haystack: str) -> bool:
    """Whether `text` (ignoring case) occurs in any of `haystack`; a blank `text` matches everything."""
    if not text or not text.strip():
        return True
    wanted = text.strip().lower()
    return any(wanted in value.lower() for value in haystack)


def filter_elements(
    elements: list[ArchitectureElement], *, status_: str | None = None, element_type_id: uuid.UUID | None = None,
    parent_id: uuid.UUID | None = None, roots_only: bool = False, open_only: bool = False, search: str | None = None,
) -> list[ArchitectureElement]:
    """The elements the list's filters keep. `open_only` leaves out retired elements; `roots_only` keeps elements
    with no parent; `parent_id` keeps the direct children of one element."""
    return [
        e for e in elements
        if (status_ is None or e.status == status_)
        and (element_type_id is None or e.element_type_id == element_type_id)
        and (parent_id is None or e.parent_id == parent_id)
        and (not roots_only or e.parent_id is None)
        and (not open_only or e.status != RecordStatus.RETIRED.value)
        and _matches(search, e.unique_code, e.name, e.description)
    ]


def filter_connections(
    connections: list[ArchitectureConnection], *, status_: str | None = None, connection_type_id: uuid.UUID | None = None,
    element_id: uuid.UUID | None = None, open_only: bool = False, search: str | None = None,
) -> list[ArchitectureConnection]:
    """The connections the list's filters keep. `element_id` keeps those with that element at either end."""
    return [
        c for c in connections
        if (status_ is None or c.status == status_)
        and (connection_type_id is None or c.connection_type_id == connection_type_id)
        and (element_id is None or element_id in (c.source_element_id, c.target_element_id))
        and (not open_only or c.status != RecordStatus.RETIRED.value)
        and _matches(search, c.unique_code, c.name, c.protocol, c.description)
    ]


def add_record_routes(router: APIRouter) -> None:
    """Adds the element, port and connection routes to `router` (the project router)."""
    view_elements = require_project_subcomponent_enabled(ARCHITECTURE_MODULE_KEY, ELEMENT_SUBCOMPONENT_KEY)
    view_connections = require_project_subcomponent_enabled(ARCHITECTURE_MODULE_KEY, CONNECTION_SUBCOMPONENT_KEY)

    def element_out(db: Session, element: ArchitectureElement) -> ElementOut:
        return records.element_outs(db, [element])[0]

    def connection_out(db: Session, connection: ArchitectureConnection) -> ConnectionOut:
        return records.connection_outs(db, [connection])[0]

    # --- Elements ----------------------------------------------------------

    @router.post("/elements", response_model=ElementOut, status_code=status.HTTP_201_CREATED)
    def create_element(
        project_id: uuid.UUID, payload: ElementCreate,
        current_user: User = Depends(view_elements), db: Session = Depends(get_db),
    ):
        """Creates an element (`draft`, or `active` with `activate`). Needs the Architect role."""
        project = project_or_404(db, project_id)
        require_architect(db, current_user, project, ELEMENT_MANAGE_PERMISSION)
        element = as_http(lambda: records.create_element(db, project, current_user, payload))
        db.commit()
        return element_out(db, element)

    @router.get("/elements", response_model=list[ElementOut])
    def list_elements(
        project_id: uuid.UUID, include_archived: bool = False, status_filter: RecordStatus | None = Query(None, alias="status"),
        element_type_id: uuid.UUID | None = None, parent_id: uuid.UUID | None = None, roots_only: bool = False,
        open_only: bool = False, search: str | None = None, tag_filter: TagFilter = Depends(),
        current_user: User = Depends(view_elements), db: Session = Depends(get_db),
        project_scope: ProjectScope = Depends(),
    ):
        """The project's elements; archived ones only with `include_archived`. `parent_id` lists one element's
        children, `roots_only` the top level, `open_only` leaves out retired elements."""

        def rows_for(pid: uuid.UUID) -> list[ElementOut]:
            found = filter_elements(
                records.list_elements(db, pid, include_archived=include_archived),
                status_=status_filter.value if status_filter else None, element_type_id=element_type_id,
                parent_id=parent_id, roots_only=roots_only, open_only=open_only, search=search,
            )
            return records.element_outs(db, tag_filter.keep(db, pid, ELEMENT_ARTEFACT_TYPE, found))

        return project_scope.collect(
            db, project_or_404(db, project_id), current_user.id, ELEMENT_ARTEFACT_TYPE, rows_for,
            gate=(ARCHITECTURE_MODULE_KEY, ELEMENT_SUBCOMPONENT_KEY),
        )

    @router.get("/elements/{element_id}", response_model=ElementOut)
    def get_element(
        project_id: uuid.UUID, element_id: uuid.UUID,
        current_user: User = Depends(view_elements), db: Session = Depends(get_db),
    ):
        """One element with its ports."""
        return element_out(db, as_http(lambda: records.get_element(db, project_id, element_id)))

    @router.put("/elements/{element_id}", response_model=ElementOut)
    def update_element(
        project_id: uuid.UUID, element_id: uuid.UUID, payload: ElementUpdate,
        current_user: User = Depends(view_elements), db: Session = Depends(get_db),
    ):
        """Edits an element; the body quotes the `version` it was based on (409 if stale). Needs the Architect role."""
        project = project_or_404(db, project_id)
        require_architect(db, current_user, project, ELEMENT_MANAGE_PERMISSION)
        element = as_http(lambda: records.update_element(db, project, current_user, element_id, payload))
        db.commit()
        return element_out(db, element)

    @router.post("/elements/{element_id}/status", response_model=ElementOut)
    def change_element_status(
        project_id: uuid.UUID, element_id: uuid.UUID, payload: StatusChange,
        current_user: User = Depends(view_elements), db: Session = Depends(get_db),
    ):
        """Moves an element to another status. Retiring needs every child retired or archived."""
        project = project_or_404(db, project_id)
        require_architect(db, current_user, project, ELEMENT_MANAGE_PERMISSION)
        element = as_http(lambda: records.change_element_status(
            db, project, current_user, element_id, payload.version, payload.status,
        ))
        db.commit()
        return element_out(db, element)

    @router.post("/elements/{element_id}/archive", response_model=ElementOut)
    def archive_element(
        project_id: uuid.UUID, element_id: uuid.UUID,
        current_user: User = Depends(view_elements), db: Session = Depends(get_db),
    ):
        """Archives an element (every child must be retired or archived)."""
        project = project_or_404(db, project_id)
        require_architect(db, current_user, project, ELEMENT_MANAGE_PERMISSION)
        element = as_http(lambda: records.set_element_archived(db, project, current_user, element_id, True))
        db.commit()
        return element_out(db, element)

    @router.post("/elements/{element_id}/unarchive", response_model=ElementOut)
    def unarchive_element(
        project_id: uuid.UUID, element_id: uuid.UUID,
        current_user: User = Depends(view_elements), db: Session = Depends(get_db),
    ):
        """Restores an archived element."""
        project = project_or_404(db, project_id)
        require_architect(db, current_user, project, ELEMENT_MANAGE_PERMISSION)
        element = as_http(lambda: records.set_element_archived(db, project, current_user, element_id, False))
        db.commit()
        return element_out(db, element)

    @router.delete("/elements/{element_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_element(
        project_id: uuid.UUID, element_id: uuid.UUID,
        current_user: User = Depends(view_elements), db: Session = Depends(get_db),
    ):
        """Deletes an element that has no children and no connection (409 otherwise), with its links, tags and places."""
        project = project_or_404(db, project_id)
        require_architect(db, current_user, project, ELEMENT_MANAGE_PERMISSION)
        as_http(lambda: records.delete_element(db, project, current_user, element_id))
        db.commit()

    # --- Ports -------------------------------------------------------------

    @router.post("/elements/{element_id}/ports", response_model=PortOut, status_code=status.HTTP_201_CREATED)
    def add_port(
        project_id: uuid.UUID, element_id: uuid.UUID, payload: PortCreate,
        current_user: User = Depends(view_elements), db: Session = Depends(get_db),
    ):
        """Adds a port to an element."""
        project = project_or_404(db, project_id)
        require_architect(db, current_user, project, ELEMENT_MANAGE_PERMISSION)
        port = as_http(lambda: records.add_port(db, project, current_user, element_id, payload))
        db.commit()
        return _port_out(db, port)

    @router.put("/elements/{element_id}/ports/{port_id}", response_model=PortOut)
    def update_port(
        project_id: uuid.UUID, element_id: uuid.UUID, port_id: uuid.UUID, payload: PortUpdate,
        current_user: User = Depends(view_elements), db: Session = Depends(get_db),
    ):
        """Edits a port."""
        project = project_or_404(db, project_id)
        require_architect(db, current_user, project, ELEMENT_MANAGE_PERMISSION)
        port = as_http(lambda: records.update_port(db, project, current_user, element_id, port_id, payload))
        db.commit()
        return _port_out(db, port)

    @router.delete("/elements/{element_id}/ports/{port_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_port(
        project_id: uuid.UUID, element_id: uuid.UUID, port_id: uuid.UUID,
        current_user: User = Depends(view_elements), db: Session = Depends(get_db),
    ):
        """Removes a port that no connection uses (409 otherwise)."""
        project = project_or_404(db, project_id)
        require_architect(db, current_user, project, ELEMENT_MANAGE_PERMISSION)
        as_http(lambda: records.delete_port(db, project, current_user, element_id, port_id))
        db.commit()

    # --- Connections -------------------------------------------------------

    @router.post("/connections", response_model=ConnectionOut, status_code=status.HTTP_201_CREATED)
    def create_connection(
        project_id: uuid.UUID, payload: ConnectionCreate,
        current_user: User = Depends(view_connections), db: Session = Depends(get_db),
    ):
        """Creates a connection between two elements of the project. Needs the Architect role."""
        project = project_or_404(db, project_id)
        require_architect(db, current_user, project, CONNECTION_MANAGE_PERMISSION)
        connection = as_http(lambda: records.create_connection(db, project, current_user, payload))
        db.commit()
        return connection_out(db, connection)

    @router.get("/connections", response_model=list[ConnectionOut])
    def list_connections(
        project_id: uuid.UUID, include_archived: bool = False, status_filter: RecordStatus | None = Query(None, alias="status"),
        connection_type_id: uuid.UUID | None = None, element_id: uuid.UUID | None = None, open_only: bool = False,
        search: str | None = None, tag_filter: TagFilter = Depends(),
        current_user: User = Depends(view_connections), db: Session = Depends(get_db),
        project_scope: ProjectScope = Depends(),
    ):
        """The project's connections; `element_id` lists those with that element at either end."""

        def rows_for(pid: uuid.UUID) -> list[ConnectionOut]:
            found = filter_connections(
                records.list_connections(db, pid, include_archived=include_archived),
                status_=status_filter.value if status_filter else None, connection_type_id=connection_type_id,
                element_id=element_id, open_only=open_only, search=search,
            )
            return records.connection_outs(db, tag_filter.keep(db, pid, CONNECTION_ARTEFACT_TYPE, found))

        return project_scope.collect(
            db, project_or_404(db, project_id), current_user.id, CONNECTION_ARTEFACT_TYPE, rows_for,
            gate=(ARCHITECTURE_MODULE_KEY, CONNECTION_SUBCOMPONENT_KEY),
        )

    @router.get("/connections/{connection_id}", response_model=ConnectionOut)
    def get_connection(
        project_id: uuid.UUID, connection_id: uuid.UUID,
        current_user: User = Depends(view_connections), db: Session = Depends(get_db),
    ):
        """One connection."""
        return connection_out(db, as_http(lambda: records.get_connection(db, project_id, connection_id)))

    @router.put("/connections/{connection_id}", response_model=ConnectionOut)
    def update_connection(
        project_id: uuid.UUID, connection_id: uuid.UUID, payload: ConnectionUpdate,
        current_user: User = Depends(view_connections), db: Session = Depends(get_db),
    ):
        """Edits a connection; the body quotes the `version` it was based on (409 if stale)."""
        project = project_or_404(db, project_id)
        require_architect(db, current_user, project, CONNECTION_MANAGE_PERMISSION)
        connection = as_http(lambda: records.update_connection(db, project, current_user, connection_id, payload))
        db.commit()
        return connection_out(db, connection)

    @router.post("/connections/{connection_id}/status", response_model=ConnectionOut)
    def change_connection_status(
        project_id: uuid.UUID, connection_id: uuid.UUID, payload: StatusChange,
        current_user: User = Depends(view_connections), db: Session = Depends(get_db),
    ):
        """Moves a connection to another status."""
        project = project_or_404(db, project_id)
        require_architect(db, current_user, project, CONNECTION_MANAGE_PERMISSION)
        connection = as_http(lambda: records.change_connection_status(
            db, project, current_user, connection_id, payload.version, payload.status,
        ))
        db.commit()
        return connection_out(db, connection)

    @router.post("/connections/{connection_id}/archive", response_model=ConnectionOut)
    def archive_connection(
        project_id: uuid.UUID, connection_id: uuid.UUID,
        current_user: User = Depends(view_connections), db: Session = Depends(get_db),
    ):
        """Archives a connection."""
        project = project_or_404(db, project_id)
        require_architect(db, current_user, project, CONNECTION_MANAGE_PERMISSION)
        connection = as_http(lambda: records.set_connection_archived(db, project, current_user, connection_id, True))
        db.commit()
        return connection_out(db, connection)

    @router.post("/connections/{connection_id}/unarchive", response_model=ConnectionOut)
    def unarchive_connection(
        project_id: uuid.UUID, connection_id: uuid.UUID,
        current_user: User = Depends(view_connections), db: Session = Depends(get_db),
    ):
        """Restores an archived connection (both ends must be unarchived)."""
        project = project_or_404(db, project_id)
        require_architect(db, current_user, project, CONNECTION_MANAGE_PERMISSION)
        connection = as_http(lambda: records.set_connection_archived(db, project, current_user, connection_id, False))
        db.commit()
        return connection_out(db, connection)

    @router.delete("/connections/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_connection(
        project_id: uuid.UUID, connection_id: uuid.UUID,
        current_user: User = Depends(view_connections), db: Session = Depends(get_db),
    ):
        """Deletes a connection with its links, tags and places."""
        project = project_or_404(db, project_id)
        require_architect(db, current_user, project, CONNECTION_MANAGE_PERMISSION)
        as_http(lambda: records.delete_connection(db, project, current_user, connection_id))
        db.commit()


def _port_out(db: Session, port: Any) -> PortOut:
    """A port's API shape with its connection type's name."""
    from app.modules.architecture.models import ArchitectureConnectionType

    names = {}
    if port.connection_type_id is not None:
        row = db.get(ArchitectureConnectionType, port.connection_type_id)
        names[port.connection_type_id] = row.name if row else ""
    return records.port_out(port, names)
