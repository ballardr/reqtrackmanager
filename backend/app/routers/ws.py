"""
Module: routers.ws

Optional WebSocket interface for live requirement/change-request state
updates (I-A-04). Browsers cannot set an Authorization header on a
WebSocket handshake, so a credential is passed as a query parameter
instead — and a URL is logged, so it is the short-lived media token
(`POST /api/v1/auth/media-token`, `security.create_media_token`), never the session token.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from app.database import SessionLocal
from app.models.project import ProjectGroup, ProjectGroupMember, UserProjectRole
from app.models.user import User
from app.security import decode_access_token
from app.services import pubsub
from app.services.rbac import _project_organization_id, is_org_active

router = APIRouter(tags=["realtime"])

# How often the receive loop wakes (even with no incoming message) to check whether the connection's token
# has expired and the account is still active, bounding the exposure window described in the
# connection-lifetime docstring below without a periodic re-auth round-trip.
_EXPIRY_CHECK_INTERVAL_SECONDS = 60


def _user_session_still_valid(user_id: UUID, token_version: int, organization_id: UUID | None) -> bool:
    """Re-checks `User.is_active`, `User.token_version` and (if the project still resolves to an organisation)
    `Organization.is_active` in a fresh, short-lived session, used by the periodic recheck rather than
    holding one DB session open for a connection's whole (potentially hours-long) lifetime.

    The `token_version` comparison is what makes password-change/2FA-disable close an already-open socket, the
    guarantee `deps._resolve_user_from_token` gives every REST request; `token_version` is this system's
    primary technical incident-containment tool (access-control-policy.md) and must apply to WebSocket
    connections.

    The `organization_id`/`is_org_active` check applies the same rule: disabling an organisation locks out
    access "regardless of the caller's role, including the org's own admins" (`rbac._require_org_active`), so an
    already-open socket streaming that org's project updates must close too.
    """
    db = SessionLocal()
    try:
        row = db.execute(select(User.is_active, User.token_version).where(User.id == user_id)).first()
        if row is None or not row.is_active or row.token_version != token_version:
            return False
        return organization_id is None or is_org_active(db, organization_id)
    finally:
        db.close()


@router.websocket("/ws/projects/{project_id}")
async def project_updates(websocket: WebSocket, project_id: UUID, token: str = Query(...)):
    """Streams JSON messages for requirement/change-request state changes.

    Message shape: {"type": "requirement" | "change_request", "action": str, "id": str}

    Access is checked once at handshake time; token expiry, `token_version` revocation (password change / 2FA
    disable), account deactivation and the project's organisation being disabled are then rechecked every
    `_EXPIRY_CHECK_INTERVAL_SECONDS`, so a deactivated or credential-revoked account's (or disabled org's)
    open socket closes within one interval, as the REST API rejects a stale token or `is_active=False` on every
    request. Project role changes are not rechecked mid-connection: a downgrade or removal takes effect on the
    next REST call, but an open socket keeps streaming that project's updates until the connection's token
    expires, is revoked, or the account is deactivated or archived.
    """
    claims = decode_access_token(token)
    if not claims or "sub" not in claims or claims.get("purpose") != "media":
        await websocket.close(code=4401)
        return
    token_version = claims.get("tv", 0)
    token_expires_at = datetime.fromtimestamp(claims["exp"], tz=UTC) if "exp" in claims else None

    db = SessionLocal()
    try:
        user = db.get(User, UUID(claims["sub"]))
        if user is not None and user.token_version != token_version:
            # Token issued before the user's latest password change / 2FA disable (`User.token_version`):
            # rejected as `deps._resolve_user_from_token` does for REST, though signature and expiry are valid.
            user = None
        # No server-admin bypass (I-M-05): live project updates are "data
        # within organisations", same boundary as every REST endpoint.
        organization_id = _project_organization_id(db, project_id)
        # A disabled organisation blocks access for everyone, including its own admins
        # (rbac._require_org_active); checked here because this handler authorises inline rather than through a
        # require_* dependency factory. A nonexistent project (organization_id is None) falls through to the
        # ordinary "no role" rejection rather than being reported as "organisation disabled".
        org_active = organization_id is None or is_org_active(db, organization_id)
        has_access = (
            user is not None
            and org_active
            and (
                db.scalar(
                    select(UserProjectRole).where(
                        UserProjectRole.user_id == user.id, UserProjectRole.project_id == project_id
                    )
                )
                is not None
                or db.scalar(
                    select(ProjectGroupMember)
                    .join(ProjectGroup, ProjectGroup.id == ProjectGroupMember.project_group_id)
                    .where(ProjectGroup.project_id == project_id, ProjectGroupMember.user_id == user.id)
                )
                is not None
            )
        )
    finally:
        db.close()

    if user is None:
        await websocket.close(code=4401)
        return
    if not has_access:
        await websocket.close(code=4403)
        return

    await pubsub.connect(project_id, websocket)
    try:
        while True:
            if token_expires_at is not None and datetime.now(UTC) >= token_expires_at:
                await websocket.close(code=4401)
                break
            try:
                await asyncio.wait_for(websocket.receive_text(), timeout=_EXPIRY_CHECK_INTERVAL_SECONDS)
            except TimeoutError:
                if not _user_session_still_valid(user.id, token_version, organization_id):
                    await websocket.close(code=4401)
                    break
                continue  # still active and not revoked — loop back to the expiry check
    except WebSocketDisconnect:
        pass
    finally:
        pubsub.disconnect(project_id, websocket)
