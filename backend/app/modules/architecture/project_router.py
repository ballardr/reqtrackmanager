"""
Module: modules.architecture.project_router

Project-scoped API of the Architecture module, mounted at
`/api/v1/projects/{project_id}/modules/architecture`: the project's effective
element types, connection types and symbols, its own rows, hiding and restoring the
organisation's defaults, and the project's elements, ports and connections
(`record_routes`), collections (`collection_routes`) and diagrams (`diagram_routes`).

RBAC: the record type's sub-component and project membership to read; a
vocabulary change needs `_shared.require_architecture_admin` and a record change
`_shared.require_architect`.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.modules.architecture import _shared as sh
from app.modules.architecture import symbol_routes, vocabulary_routes
from app.modules.architecture.allocation_routes import add_allocation_routes
from app.modules.architecture.collection_routes import add_project_collection_routes
from app.modules.architecture.comments import add_comment_routes
from app.modules.architecture.diagram_routes import add_diagram_routes
from app.modules.architecture.folder_routes import add_project_folder_routes
from app.modules.architecture.record_routes import add_record_routes
from app.modules.architecture.reports import REPORT_ROUTERS
from app.modules.architecture.schemas import (
    CapabilitiesOut,
    ConnectionTypeCreate,
    ConnectionTypeOut,
    ConnectionTypeUpdate,
    ElementTypeCreate,
    ElementTypeOut,
    ElementTypeUpdate,
    SymbolOut,
    SymbolUpdate,
)
from app.modules.architecture.service import (
    ARCHITECTURE_MODULE_KEY,
    CONNECTION_TYPES,
    ELEMENT_TYPES,
    SYMBOLS,
    TYPE_SUBCOMPONENT_KEY,
)
from app.modules.architecture.state_machine_routes import add_state_machine_routes
from app.services.rbac import require_project_subcomponent_enabled

router = APIRouter(
    prefix=f"/api/v1/projects/{{project_id}}/modules/{ARCHITECTURE_MODULE_KEY}", tags=["architecture-project"],
)

_require_view = require_project_subcomponent_enabled(ARCHITECTURE_MODULE_KEY, TYPE_SUBCOMPONENT_KEY)

vocabulary_routes.add_project_routes(
    router, path="element-types", vocabulary=ELEMENT_TYPES, create_schema=ElementTypeCreate,
    update_schema=ElementTypeUpdate, out_schema=ElementTypeOut, entity_type="architecture_element_type",
    require_view=_require_view,
)
vocabulary_routes.add_project_routes(
    router, path="connection-types", vocabulary=CONNECTION_TYPES, create_schema=ConnectionTypeCreate,
    update_schema=ConnectionTypeUpdate, out_schema=ConnectionTypeOut, entity_type="architecture_connection_type",
    require_view=_require_view,
)
vocabulary_routes.add_project_routes(
    router, path="symbols", vocabulary=SYMBOLS, create_schema=None, update_schema=SymbolUpdate, out_schema=SymbolOut,
    entity_type="architecture_symbol", require_view=_require_view, create_route=False,
)
symbol_routes.add_project_symbol_routes(router, require_view=_require_view)



@router.get("/capabilities", response_model=CapabilitiesOut)
def get_capabilities(project_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db)):
    """What the caller may change in this project (today whether they may manage its types), for screens that show an
    action only to someone it will work for. Open to any project member; the actions themselves still enforce the role."""
    project = sh.get_project(db, project_id)
    try:
        sh.require_architecture_admin(db, current_user, project)
    except HTTPException:
        return CapabilitiesOut(manage_types=False)
    return CapabilitiesOut(manage_types=True)


add_record_routes(router)
add_diagram_routes(router)
add_state_machine_routes(router)
add_comment_routes(router)
add_allocation_routes(router)
router.include_router(REPORT_ROUTERS.project)
add_project_collection_routes(router)
add_project_folder_routes(router)
