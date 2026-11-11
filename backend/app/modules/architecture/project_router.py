"""
Module: modules.architecture.project_router

Project-scoped API of the Architecture module, mounted at
`/api/v1/projects/{project_id}/modules/architecture`: the project's effective
element types and connection types, its own rows, and hiding and restoring the
organisation's defaults.

RBAC: the `architecture_type` sub-component and project membership to read;
every change needs `_shared.require_architecture_admin`.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.modules.architecture import vocabulary_routes
from app.modules.architecture.schemas import (
    ConnectionTypeCreate,
    ConnectionTypeOut,
    ConnectionTypeUpdate,
    ElementTypeCreate,
    ElementTypeOut,
    ElementTypeUpdate,
)
from app.modules.architecture.service import (
    ARCHITECTURE_MODULE_KEY,
    CONNECTION_TYPES,
    ELEMENT_TYPES,
    TYPE_SUBCOMPONENT_KEY,
)
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
