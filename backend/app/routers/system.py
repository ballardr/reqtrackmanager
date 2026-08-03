"""
Module: routers.system

Server-admin-only system management endpoints that are not scoped to any
single organisation (I-M-06): granting or revoking the server admin role
itself on another user, and the system-wide user access-review directory
(C-A-13) added in Massif (v3).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import exists, select, true
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.organization import UserOrgRole
from app.models.user import User
from app.schemas.pat import BulkRevokeResult
from app.services.audit import log_event
from app.services.pats import revoke_matching
from app.services.rbac import require_server_admin

router = APIRouter(prefix="/api/v1/system", tags=["system"])


class ServerAdminUpdate(BaseModel):
    """Payload for granting/revoking the server admin role.

    Attributes:
        is_server_admin: The desired server-admin state for the target user.
    """

    is_server_admin: bool


class SystemUserOut(BaseModel):
    """Account-level fields only (I-M-05: server admin "does not give access
    to data within organisations") — deliberately omits org role and project
    access, which only have meaning scoped to a specific organisation and
    would leak cross-tenant membership if surfaced here."""

    user_id: UUID
    email: str
    display_name: str
    is_active: bool
    last_login_at: datetime | None = None
    is_2fa_enabled: bool
    created_at: datetime


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


@router.get("/users", response_model=list[SystemUserOut])
def list_system_users(
    no_org_membership: bool | None = None,
    stale_since_days: int | None = Query(None, ge=0),
    is_active: bool | None = None,
    has_2fa: bool | None = None,
    current_user: User = Depends(require_server_admin),
    db: Session = Depends(get_db),
):
    """System-wide user directory for the server-admin access review (C-A-13).

    `no_org_membership` is the requirement's literal "orphaned account"
    clarification: an enabled user who belongs to no organisation and
    therefore has no project access either (C-U-02: all project users must
    be organisation users). Server-admin only (`require_server_admin`, no
    org-admin fallback) — this spans every organisation's users.
    """
    query = select(User).where(User.is_archived.is_(False))
    if no_org_membership:
        has_org_role = exists().where(UserOrgRole.user_id == User.id)
        query = query.where(~has_org_role)
    if is_active is not None:
        query = query.where(User.is_active == is_active)
    if has_2fa is not None:
        query = query.where(User.is_2fa_enabled == has_2fa)
    if stale_since_days is not None:
        cutoff = datetime.now(UTC) - timedelta(days=stale_since_days)
        query = query.where((User.last_login_at.is_(None)) | (User.last_login_at < cutoff))

    users = db.scalars(query).all()
    return [
        SystemUserOut(
            user_id=u.id, email=u.email, display_name=u.display_name, is_active=u.is_active,
            last_login_at=u.last_login_at, is_2fa_enabled=u.is_2fa_enabled, created_at=u.created_at,
        )
        for u in users
    ]


@router.post("/pats/revoke-all", response_model=BulkRevokeResult)
def revoke_all_pats_platform_wide(
    current_user: User = Depends(require_server_admin),
    db: Session = Depends(get_db),
):
    """Revokes every non-revoked Personal Access Token in the deployment,
    regardless of scope — an incident-response action, the PAT-level
    equivalent of the per-user `User.token_version` "kill all my sessions"
    mechanism, at platform scope. Never reads or exposes any organisation's
    content or any token secret (hashes aren't reversible), so this is pure
    security/tenancy administration and doesn't conflict with I-M-05."""
    count = revoke_matching(db, true())
    log_event(db, entity_type="system", entity_id="platform", action="system_pats_bulk_revoked",
              actor_id=current_user.id, detail={"count": count})
    db.commit()
    return BulkRevokeResult(revoked_count=count)
