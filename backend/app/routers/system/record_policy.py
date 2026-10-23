"""
Module: routers.system.record_policy

Server administration of the personal-data policy for record export and import: the deployment-wide
default per sensitivity tag (`services.record_policy`). Organisations may override it
(`routers.orgs.record_policy`).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.schemas.record_policy import ServerSensitivityOut, ServerSensitivityUpdate
from app.services.rbac import require_server_admin
from app.services.record_policy import server_defaults, set_server_default

router = APIRouter(tags=["system-record-policy"])


@router.get("/record-sensitivity-policy", response_model=list[ServerSensitivityOut])
def list_server_sensitivity_policy(
    current_user: User = Depends(require_server_admin), db: Session = Depends(get_db),
) -> list[ServerSensitivityOut]:
    """The server default per sensitivity tag; a tag nobody has opted into is excluded."""
    return [ServerSensitivityOut(tag=tag, allowed=allowed) for tag, allowed in server_defaults(db).items()]


@router.put("/record-sensitivity-policy/{tag}", response_model=ServerSensitivityOut)
def update_server_sensitivity_policy(
    tag: str, payload: ServerSensitivityUpdate,
    current_user: User = Depends(require_server_admin), db: Session = Depends(get_db),
) -> ServerSensitivityOut:
    """Sets the server default for one tag. Organisations with their own override keep it; the rest follow.

    Raises:
        HTTPException: 404 for an unknown tag.
    """
    try:
        set_server_default(db, tag, payload.allowed, current_user.id)
    except ValueError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown sensitivity tag.") from None
    db.commit()
    return ServerSensitivityOut(tag=tag, allowed=payload.allowed)
