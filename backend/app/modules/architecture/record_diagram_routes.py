"""
Module: modules.architecture.record_diagram_routes

The read endpoints behind the Diagrams card of an element or connection page, added to the module's project router by
`add_record_diagram_routes`: `GET /elements/{id}/diagrams` and `GET /connections/{id}/diagrams`.

Responsibilities:
- Read the record through the same gate as its own page (`records.read_element` for an element, so a hidden one is a 404;
  the project's connection for a connection) and answer `record_diagrams`' list.
- Offer each diagram type only to a caller whose project has its sub-component enabled.

RBAC: project membership and the record type's sub-component, as the record's own read. The card is read-only.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.modules.architecture import record_diagrams, records
from app.modules.architecture.record_routes import as_http
from app.modules.architecture.schemas import RecordDiagramOut
from app.modules.architecture.service import (
    ARCHITECTURE_MODULE_KEY,
    CONNECTION_SUBCOMPONENT_KEY,
    DIAGRAM_SUBCOMPONENT_KEY,
    ELEMENT_SUBCOMPONENT_KEY,
    STATE_MACHINE_SUBCOMPONENT_KEY,
)
from app.modules.architecture.visibility import Viewer
from app.modules.registry import is_module_subcomponent_enabled
from app.services.lookups import project_or_404
from app.services.rbac import require_project_subcomponent_enabled


def add_record_diagram_routes(router: APIRouter) -> None:
    """Adds the Diagrams card reads to `router` (the project router)."""
    view_elements = require_project_subcomponent_enabled(ARCHITECTURE_MODULE_KEY, ELEMENT_SUBCOMPONENT_KEY)
    view_connections = require_project_subcomponent_enabled(ARCHITECTURE_MODULE_KEY, CONNECTION_SUBCOMPONENT_KEY)

    @router.get("/elements/{element_id}/diagrams", response_model=list[RecordDiagramOut])
    def get_element_diagrams(
        project_id: uuid.UUID, element_id: uuid.UUID,
        current_user: User = Depends(view_elements), db: Session = Depends(get_db),
    ):
        """The block diagrams that draw the element (its own box, or an ancestor's) and the state machine diagrams that
        describe it. 404 for an element the caller may not read; a diagram type whose sub-component is off is absent."""
        project = project_or_404(db, project_id)
        viewer = Viewer.of_user(current_user, project)
        element = as_http(lambda: records.read_element(db, viewer, element_id))
        return record_diagrams.element_diagrams(
            db, viewer, project.id, element,
            blocks=is_module_subcomponent_enabled(db, project.id, ARCHITECTURE_MODULE_KEY, DIAGRAM_SUBCOMPONENT_KEY),
            machines=is_module_subcomponent_enabled(db, project.id, ARCHITECTURE_MODULE_KEY, STATE_MACHINE_SUBCOMPONENT_KEY),
        )

    @router.get("/connections/{connection_id}/diagrams", response_model=list[RecordDiagramOut])
    def get_connection_diagrams(
        project_id: uuid.UUID, connection_id: uuid.UUID,
        current_user: User = Depends(view_connections), db: Session = Depends(get_db),
    ):
        """The block diagrams that draw the connection, including as a line rolled up to ancestors of its ends. Empty
        when the diagram sub-component is off."""
        project = project_or_404(db, project_id)
        connection = as_http(lambda: records.get_connection(db, project.id, connection_id))
        if not is_module_subcomponent_enabled(db, project.id, ARCHITECTURE_MODULE_KEY, DIAGRAM_SUBCOMPONENT_KEY):
            return []
        return record_diagrams.connection_diagrams(db, project.id, connection)
