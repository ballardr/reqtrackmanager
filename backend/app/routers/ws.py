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
from app.services.rbac import _project_organization_id, is_org_active

router = APIRouter(tags=["realtime"])

# How often the receive loop wakes up (even with no incoming message) to
# check whether the connection's token has expired and whether the account
# is still active. Bounds the exposure window described in the
# connection-lifetime docstring below without needing a full periodic
# re-auth round-trip.
_EXPIRY_CHECK_INTERVAL_SECONDS = 60


def _user_session_still_valid(user_id: UUID, token_version: int, organization_id: UUID | None) -> bool:
    """Re-checks `User.is_active`, `User.token_version`, and (if the project
    still resolves to an organisation) `Organization.is_active` in a fresh,
    short-lived session — used by the periodic recheck below rather than
    holding one DB session open for a connection's entire (potentially
    hours-long) lifetime.

    The `token_version` comparison is what makes password-change/2FA-disable
    actually close an already-open socket, the same guarantee
    `deps._resolve_user_from_token` already provides for every REST
    request — a hardening-review finding: this function previously checked
    only `is_active`, so `token_version`'s documented role as "this
    system's primary technical incident-containment tool"
    (access-control-policy.md) silently did not apply to WebSocket
    connections at all, despite docs/decisions.md claiming this exact gap
    was already closed.

    The `organization_id`/`is_org_active` check was added by a later
    hardening pass for the same reason: disabling an organisation is
    documented to lock out access "regardless of the caller's role,
    including the org's own admins" (`rbac._require_org_active`), and an
    already-open socket streaming that org's project updates was a full,
    silent exception to that guarantee until this was added.
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

    Access is checked once at handshake time; token expiry, `token_version`
    revocation (password change / 2FA disable), account deactivation, and
    the project's organisation being disabled are then rechecked every
    `_EXPIRY_CHECK_INTERVAL_SECONDS` (SOC 2 access-control hardening pass —
    a deactivated/credential-revoked account's or now-disabled org's
    already-open socket closes within one interval, matching the REST
    API's behaviour of rejecting a stale token / `is_active=False` on
    every request, rather than only once the token naturally expires).
    Project *role* changes are still not rechecked mid-connection —
    narrowing, not eliminating, the original exposure window: a role
    downgrade/removal takes effect on the next REST call immediately, but
    an already-open socket keeps streaming that project's updates until
    the connection's token expires, is revoked, or the account itself is
    deactivated/archived.
    """
    claims = decode_access_token(token)
    if not claims or "sub" not in claims or claims.get("purpose") != "access":
        await websocket.close(code=4401)
        return
    token_version = claims.get("tv", 0)
    token_expires_at = datetime.fromtimestamp(claims["exp"], tz=UTC) if "exp" in claims else None

    db = SessionLocal()
    try:
        user = db.get(User, UUID(claims["sub"]))
        if user is not None and user.token_version != token_version:
            # Token was issued before the user's most recent password
            # change / 2FA disable (see User.token_version) — reject
            # exactly like deps._resolve_user_from_token does for REST,
            # even though the signature/expiry are otherwise valid.
            user = None
        # No server-admin bypass (I-M-05): live project updates are "data
        # within organisations", same boundary as every REST endpoint.
        organization_id = _project_organization_id(db, project_id)
        # A disabled organisation blocks access for everyone, including its
        # own admins (rbac._require_org_active) — checked here too, since
        # this handler authorizes inline rather than through one of the
        # require_* dependency factories that check does automatically. A
        # nonexistent project (organization_id is None) is left to fall
        # through to the ordinary "no role" rejection below rather than
        # being misreported as "organisation disabled".
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
