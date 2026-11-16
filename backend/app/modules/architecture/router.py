"""
Module: modules.architecture.router

Organisation-scoped API of the Architecture module, mounted at
`/api/v1/orgs/{organization_id}/modules/architecture`: the organisation's default
element types, connection types and symbols, its own elements and its collections.

RBAC: the `architecture_type` sub-component to read; every change needs
`_shared.require_architecture_org_admin`.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.modules.architecture import _shared as sh
from app.modules.architecture import symbol_routes, vocabulary_routes
from app.modules.architecture.collection_routes import add_org_collection_routes
from app.modules.architecture.folder_routes import add_org_folder_routes
from app.modules.architecture.record_routes import add_org_record_routes
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
from app.services.rbac import require_org_subcomponent_enabled

router = APIRouter(
    prefix=f"/api/v1/orgs/{{organization_id}}/modules/{ARCHITECTURE_MODULE_KEY}", tags=["architecture-org"],
)

_require_view = require_org_subcomponent_enabled(ARCHITECTURE_MODULE_KEY, TYPE_SUBCOMPONENT_KEY)


@router.get("/capabilities", response_model=CapabilitiesOut)
def get_org_capabilities(organization_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db)):
    """What the caller may change in this organisation (today whether they may manage its default types and symbols),
    for screens that show an action only to someone it will work for. Open to anyone who may read the organisation's
    types; the actions themselves still enforce `architecture_org_admin`."""
    try:
        sh.require_architecture_org_admin(db, current_user, organization_id=organization_id)
    except HTTPException:
        return CapabilitiesOut(manage_types=False)
    return CapabilitiesOut(manage_types=True)

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
add_org_folder_routes(router)
