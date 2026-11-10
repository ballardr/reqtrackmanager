"""
Module: routers.system.access

The caller's own server-tier access, so the interface shows an
administration section only to someone who may use it. The answer comes
from the same role check the protected routes use (`services.rbac`), never
from a client-side guess.

Responsibilities:
- `GET /system/access`: the roles the caller holds and which server
  administration sections each unlocks.

Design: any authenticated user may read their own access (it carries no
other person's data), and a personal access token reads an empty answer
because a token can never satisfy a server-tier check.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models.enums import ServerRole
from app.models.user import User
from app.services.rbac import get_granted_server_roles

router = APIRouter(tags=["system-access"])


class ServerAccessOut(BaseModel):
    """The caller's server-tier access.

    Attributes:
        roles: Every server role the caller holds (`server_admin` included
            for a server administrator).
        can_view_organizations: May open the Organisations page (find the
            target of a subscription action).
        can_create_organizations: May create, import, suspend and enable.
        can_delete_organizations: May delete an organisation.
        can_manage_entitlements: May read and set an organisation's module
            entitlements.
        can_administer_server: Is a server administrator (every other
            Server Management section).
    """

    roles: list[ServerRole]
    can_view_organizations: bool
    can_create_organizations: bool
    can_delete_organizations: bool
    can_manage_entitlements: bool
    can_administer_server: bool


@router.get("/access", response_model=ServerAccessOut)
def read_my_server_access(
    request: Request, current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
) -> ServerAccessOut:
    """Returns the caller's server roles and the sections they unlock.

    Args:
        request: The request (a personal access token gets no server access).
        current_user: The authenticated caller.
        db: Database session.

    Returns:
        The caller's server-tier access.
    """
    if getattr(request.state, "pat_allowed_org_ids", None) is not None:
        return ServerAccessOut(
            roles=[], can_view_organizations=False, can_create_organizations=False,
            can_delete_organizations=False, can_manage_entitlements=False, can_administer_server=False,
        )
    admin = current_user.is_server_admin
    granted = get_granted_server_roles(db, current_user)
    manager = admin or ServerRole.SUBSCRIPTION_MANAGER in granted
    remover = admin or ServerRole.SUBSCRIPTION_REMOVAL_AUTHORITY in granted
    roles = sorted(granted, key=lambda r: r.value)
    if admin:
        roles = [ServerRole.SERVER_ADMIN, *roles]
    return ServerAccessOut(
        roles=roles,
        can_view_organizations=manager or remover,
        can_create_organizations=manager,
        can_delete_organizations=remover,
        can_manage_entitlements=admin or bool(granted & {ServerRole.MODULE_ADMINISTRATOR, ServerRole.SUBSCRIPTION_MANAGER}),
        can_administer_server=admin,
    )
