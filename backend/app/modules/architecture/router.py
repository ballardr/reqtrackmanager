"""
Module: modules.architecture.router

Organisation-scoped API of the Architecture module, mounted at
`/api/v1/orgs/{organization_id}/modules/architecture`: the organisation's default
element types, connection types and symbols, its own elements and its collections.

RBAC: the `architecture_type` sub-component to read; every change needs
`_shared.require_architecture_org_admin`.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.modules.architecture import symbol_routes, vocabulary_routes
from app.modules.architecture.collection_routes import add_org_collection_routes
from app.modules.architecture.record_routes import add_org_record_routes
from app.modules.architecture.schemas import (
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
from app.services.rbac import require_org_subcomponent_enabled

router = APIRouter(
    prefix=f"/api/v1/orgs/{{organization_id}}/modules/{ARCHITECTURE_MODULE_KEY}", tags=["architecture-org"],
)

_require_view = require_org_subcomponent_enabled(ARCHITECTURE_MODULE_KEY, TYPE_SUBCOMPONENT_KEY)

vocabulary_routes.add_org_routes(
    router, path="element-types", vocabulary=ELEMENT_TYPES, create_schema=ElementTypeCreate,
    update_schema=ElementTypeUpdate, out_schema=ElementTypeOut, entity_type="architecture_element_type",
    require_view=_require_view,
)
vocabulary_routes.add_org_routes(
    router, path="connection-types", vocabulary=CONNECTION_TYPES, create_schema=ConnectionTypeCreate,
    update_schema=ConnectionTypeUpdate, out_schema=ConnectionTypeOut, entity_type="architecture_connection_type",
    require_view=_require_view,
)
vocabulary_routes.add_org_routes(
    router, path="symbols", vocabulary=SYMBOLS, create_schema=None, update_schema=SymbolUpdate, out_schema=SymbolOut,
    entity_type="architecture_symbol", require_view=_require_view, create_route=False,
)
symbol_routes.add_org_symbol_routes(router, require_view=_require_view)
add_org_record_routes(router)
add_org_collection_routes(router)
