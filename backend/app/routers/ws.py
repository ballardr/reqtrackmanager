"""
Module: routers.ws

Optional WebSocket interface for live requirement/change-request state
updates (I-A-04). Browsers cannot set an Authorization header on a
WebSocket handshake, so the access token is passed as a query parameter
instead.
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

router = APIRouter(tags=["realtime"])

# How often the receive loop wakes up (even with no incoming message) to
# check whether the connection's token has expired. Bounds the exposure
# window described in the connection-lifetime docstring below without
# needing a full periodic re-auth round-trip.
_EXPIRY_CHECK_INTERVAL_SECONDS = 60


@router.websocket("/ws/projects/{project_id}")
async def project_updates(websocket: WebSocket, project_id: UUID, token: str = Query(...)):
    """Streams JSON messages for requirement/change-request state changes.

    Message shape: {"type": "requirement" | "change_request", "action": str, "id": str}

    Access is checked once at handshake time and then never again for the
    life of the connection — a plain `while True: await receive_text()` loop
    has no way to notice a subsequent token expiry, role revocation, or
    account deactivation on its own. That means a long-lived connection
    opened right after login could keep streaming project updates well past
    the point the REST API would start rejecting the same token (which
    re-checks `is_active`/role fresh on every request). This handler closes
    the socket once the *original* token's own `exp` is reached, capping the
    exposure window to the token's normal lifetime rather than leaving it
    unbounded — it does not re-check role/`is_active` mid-connection, since
    that would need a DB round-trip on every check interval; expiry is the
    cheap, always-available bound.
    """
    claims = decode_access_token(token)
    if not claims or "sub" not in claims or claims.get("purpose") != "access":
        await websocket.close(code=4401)
        return
    token_expires_at = datetime.fromtimestamp(claims["exp"], tz=UTC) if "exp" in claims else None

    db = SessionLocal()
    try:
        user = db.get(User, UUID(claims["sub"]))
        # No server-admin bypass (I-M-05): live project updates are "data
        # within organisations", same boundary as every REST endpoint.
        has_access = user is not None and (
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
    finally:
        db.close()

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
            except asyncio.TimeoutError:
                continue  # no message within the interval — loop back to the expiry check
    except WebSocketDisconnect:
        pass
    finally:
        pubsub.disconnect(project_id, websocket)
