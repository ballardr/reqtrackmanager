"""
Module: routers.system

Server-admin-only system management endpoints that are not scoped to any
single organisation (I-M-06): granting or revoking the server admin role
itself on another user.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.services.audit import log_event
from app.services.rbac import require_server_admin

router = APIRouter(prefix="/api/v1/system", tags=["system"])


class ServerAdminUpdate(BaseModel):
    """Payload for granting/revoking the server admin role.

    Attributes:
        is_server_admin: The desired server-admin state for the target user.
    """

    is_server_admin: bool


@router.put("/users/{user_id}/server-admin", status_code=status.HTTP_204_NO_CONTENT)
def set_server_admin(
    user_id: UUID,
    payload: ServerAdminUpdate,
    current_user: User = Depends(require_server_admin),
    db: Session = Depends(get_db),
):
    """Grants or revokes the server admin role on another user (I-M-06).

    Only an existing server admin may call this endpoint, per the
    requirement's own wording: "This user can assign any user on the system,
    the server admin permission role."

    Args:
        user_id: The user whose server-admin flag is being changed.
        payload: The desired `is_server_admin` state.
        current_user: The calling server admin (enforced by the dependency).
        db: Active database session.

    Raises:
        HTTPException: 404 if `user_id` doesn't exist.
    """
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found.")
    target.is_server_admin = payload.is_server_admin
    log_event(
        db,
        entity_type="user",
        entity_id=user_id,
        action="server_admin_granted" if payload.is_server_admin else "server_admin_revoked",
        actor_id=current_user.id,
    )
    db.commit()
