"""
Module: routers.ws

Optional WebSocket interface for live requirement/change-request state
updates (I-A-04). Browsers cannot set an Authorization header on a
WebSocket handshake, so the access token is passed as a query parameter
instead.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from app.database import SessionLocal
from app.models.project import ProjectGroup, ProjectGroupMember, UserProjectRole
from app.models.user import User
from app.security import decode_access_token
from app.services import pubsub

router = APIRouter(tags=["realtime"])


@router.websocket("/ws/projects/{project_id}")
async def project_updates(websocket: WebSocket, project_id: UUID, token: str = Query(...)):
    """Streams JSON messages for requirement/change-request state changes.

    Message shape: {"type": "requirement" | "change_request", "action": str, "id": str}
    """
    claims = decode_access_token(token)
    if not claims or "sub" not in claims or claims.get("purpose") != "access":
        await websocket.close(code=4401)
        return

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
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        pubsub.disconnect(project_id, websocket)
