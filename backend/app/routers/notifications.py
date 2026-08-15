"""
Module: routers.notifications

In-app notification centre (C-N-02) and per-type notification preferences
(C-N-04): list my notifications, mark read, and configure UI/email delivery
per notification type.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import HTMLResponse
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.deps import get_current_user
from app.models.notification import DigestMode, Notification, NotificationPreference, NotificationType
from app.models.user import User
from app.schemas.notification import NotificationOut, NotificationPreferenceOut, NotificationPreferenceUpdate
from app.security import decode_email_unsubscribe_token
from app.services.audit import log_event
from app.services.email_branding import resolve_email_branding
from app.services.email_templates import render_page

router = APIRouter(prefix="/api/v1/notifications", tags=["notifications"])
settings = get_settings()


@router.get("", response_model=list[NotificationOut])
def list_notifications(
    response: Response,
    unread_only: bool = False,
    search: str | None = None,
    limit: int | None = Query(None, ge=1),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Lists the caller's notifications, newest first.

    `limit`/`offset` (U-P-06) are optional — omitting both preserves the
    original unbounded-fetch behaviour the dropdown bell still relies on.
    The dedicated notifications page passes both, plus `search` (matches
    title or body), for lazy-loaded browsing back through notification
    history without pulling the whole list up front. When `limit` is
    given, the total match count is returned in `X-Total-Count`, same
    convention as `list_requirements`.
    """
    query = select(Notification).where(Notification.user_id == current_user.id)
    if unread_only:
        query = query.where(Notification.read_at.is_(None))
    if search:
        needle = f"%{search.lower()}%"
        query = query.where(or_(Notification.title.ilike(needle), Notification.body.ilike(needle)))
    query = query.order_by(Notification.created_at.desc())

    if limit is None:
        return db.scalars(query).all()

    total = len(db.scalars(query).all())
    response.headers["X-Total-Count"] = str(total)
    return db.scalars(query.offset(offset).limit(limit)).all()


@router.post("/{notification_id}/read", response_model=NotificationOut)
def mark_read(notification_id: UUID, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    notification = db.get(Notification, notification_id)
    if notification is None or notification.user_id != current_user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Notification not found.")
    if notification.read_at is None:
        notification.read_at = datetime.now(UTC)
        db.commit()
        db.refresh(notification)
    return notification


@router.post("/read-all", status_code=status.HTTP_204_NO_CONTENT)
def mark_all_read(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    db.execute(
        Notification.__table__.update()
        .where(Notification.user_id == current_user.id, Notification.read_at.is_(None))
        .values(read_at=datetime.now(UTC))
    )
    db.commit()


@router.get("/preferences", response_model=list[NotificationPreferenceOut])
def list_preferences(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Returns effective preferences for every notification type (defaults to enabled)."""
    existing = {
        p.type: p
        for p in db.scalars(select(NotificationPreference).where(NotificationPreference.user_id == current_user.id)).all()
    }
    return [
        NotificationPreferenceOut(
            type=t,
            ui_enabled=existing[t].ui_enabled if t in existing else True,
            email_enabled=existing[t].email_enabled if t in existing else True,
        )
        for t in NotificationType
    ]


@router.put("/preferences/{notification_type}", response_model=NotificationPreferenceOut)
def set_preference(
    notification_type: NotificationType, payload: NotificationPreferenceUpdate,
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    pref = db.scalar(
        select(NotificationPreference).where(
            NotificationPreference.user_id == current_user.id, NotificationPreference.type == notification_type
        )
    )
    if pref is None:
        pref = NotificationPreference(user_id=current_user.id, type=notification_type)
        db.add(pref)
    pref.ui_enabled = payload.ui_enabled
    pref.email_enabled = payload.email_enabled
    db.commit()
    return NotificationPreferenceOut(type=notification_type, ui_enabled=pref.ui_enabled, email_enabled=pref.email_enabled)


# --- One-click email unsubscribe --------------------------------------------


@router.get("/unsubscribe", response_class=HTMLResponse, include_in_schema=False)
def unsubscribe(token: str, db: Session = Depends(get_db)):
    """Public, unauthenticated landing page for the "manage your email
    preferences" link in every outgoing email's footer
    (`services/notifications.py::_unsubscribe_url`,
    `security.create_email_unsubscribe_token`).

    Deliberately narrow: the token can only ever set
    `User.email_digest_mode = DigestMode.NONE` — the exact same field a
    logged-in user can already set themselves from the Preferences page
    (`PUT /auth/me`), so a one-click unsubscribe and "the login
    preferences" are provably the same state, not a parallel flag. No
    other account state is reachable through this endpoint. This is a
    deliberate, narrow exception to normal authenticated-request handling
    (mirroring the "shared UI chrome" carve-out documented in
    `docs/soc2/policies/access-control-policy.md`'s Authorization section)
    rather than a gap: an unauthenticated recipient clicking a link in
    their mail client has no session to present, so the alternative would
    be no one-click unsubscribe at all.

    Every use — successful or a rejected/expired/tampered token — writes
    an audit trail entry (`services/audit.py::log_event`) per
    `docs/soc2/policies/system-operations-monitoring-and-logging-policy.md`,
    so misuse or an unexpectedly-invalid link is visible without needing to
    reconstruct it from anything else.
    """
    user_id_str = decode_email_unsubscribe_token(token)
    user: User | None = None
    if user_id_str:
        try:
            user = db.get(User, UUID(user_id_str))
        except ValueError:
            user = None

    if user is not None:
        user.email_digest_mode = DigestMode.NONE
        log_event(
            db, entity_type="user", entity_id=user.id, action="email_unsubscribed_via_link",
            actor_id=None, detail={"result": "success"},
        )
    else:
        log_event(
            db, entity_type="user", entity_id="unknown", action="email_unsubscribe_link_rejected",
            actor_id=None, detail={"result": "invalid_or_expired_token"},
        )
    db.commit()

    branding = resolve_email_branding(db, organization_id=None)
    html = render_page(
        "unsubscribe_confirmation", branding=branding, success=user is not None,
        cta_url=f"{settings.frontend_base_url}/preferences",
    )
    return HTMLResponse(html)
