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
from sqlalchemy import false, or_, select, update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.deps import get_current_user
from app.models.notification import DigestMode, Notification, NotificationPreference
from app.models.user import User
from app.modules.registry import get_all_notification_targets, get_all_notification_types
from app.schemas.notification import (
    NotificationDetailOut,
    NotificationOut,
    NotificationPreferenceOut,
    NotificationPreferenceUpdate,
)
from app.security import decode_email_unsubscribe_token
from app.services.audit import log_event
from app.services.email_branding import resolve_email_branding
from app.services.email_templates import render_page
from app.services.notification_targets import subject_available
from app.services.rbac import restrict_to_session_scope

router = APIRouter(prefix="/api/v1/notifications", tags=["notifications"])
settings = get_settings()


def _out(notification: Notification, targets: dict[str, tuple[str, ...]] | None = None) -> NotificationOut:
    """The API shape of a notification, with the target kinds declared for its type.

    Args:
        notification: The row.
        targets: The merged target table, passed by a list so it is built once per request.

    Returns:
        The notification with `target_kinds` set (empty for a type that declares none).
    """
    out = NotificationOut.model_validate(notification)
    out.target_kinds = list((targets if targets is not None else get_all_notification_targets()).get(notification.type, ()))
    return out


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

    `limit`/`offset` (U-P-06) are optional; omitting both returns everything (as the bell dropdown does). The
    notifications page passes both, plus `search` (matches title or body). When `limit` is given the total
    match count is returned in `X-Total-Count`, as `list_requirements`.

    Types the caller has opted out of in-app (`NotificationPreference.ui_enabled` false) are excluded at
    query time; the rows are still recorded (see `services.notifications.notify`).
    """
    ui_opted_out = select(NotificationPreference.type).where(
        NotificationPreference.user_id == current_user.id, NotificationPreference.ui_enabled.is_(False)
    )
    query = select(Notification).where(Notification.user_id == current_user.id, Notification.type.not_in(ui_opted_out))
    if unread_only:
        query = query.where(Notification.read_at.is_(None))
    if search:
        needle = f"%{search.lower()}%"
        query = query.where(or_(Notification.title.ilike(needle), Notification.body.ilike(needle)))
    allowed_orgs, allowed_projects = db.info.get("pat_allowed_org_ids"), db.info.get("pat_allowed_project_ids")
    if allowed_orgs is not None or allowed_projects is not None or "module_frame_project_id" in db.info:
        # A scoped credential sees only what concerns a project it may reach, never the account-level notices.
        reachable = restrict_to_session_scope(
            db,
            {p for p in db.scalars(select(Notification.project_id).where(Notification.user_id == current_user.id).distinct()) if p},
        )
        query = query.where(Notification.project_id.in_(reachable) if reachable else false())
    query = query.order_by(Notification.created_at.desc())

    targets = get_all_notification_targets()
    if limit is None:
        return [_out(n, targets) for n in db.scalars(query).all()]

    total = len(db.scalars(query).all())
    response.headers["X-Total-Count"] = str(total)
    return [_out(n, targets) for n in db.scalars(query.offset(offset).limit(limit)).all()]


@router.post("/{notification_id}/read", response_model=NotificationOut)
def mark_read(notification_id: UUID, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    notification = db.get(Notification, notification_id)
    if notification is None or notification.user_id != current_user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Notification not found.")
    if notification.read_at is None:
        notification.read_at = datetime.now(UTC)
        db.commit()
        db.refresh(notification)
    return _out(notification)


@router.post("/read-all", status_code=status.HTTP_204_NO_CONTENT)
def mark_all_read(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    db.execute(
        update(Notification)
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
            type=t, label=label,
            ui_enabled=existing[t].ui_enabled if t in existing else True,
            email_enabled=existing[t].email_enabled if t in existing else True,
        )
        for t, label in get_all_notification_types().items()
    ]


@router.put("/preferences/{notification_type}", response_model=NotificationPreferenceOut)
def set_preference(
    notification_type: str, payload: NotificationPreferenceUpdate,
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    labels = get_all_notification_types()
    if notification_type not in labels:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown notification type.")
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
    return NotificationPreferenceOut(
        type=notification_type, label=labels[notification_type], ui_enabled=pref.ui_enabled,
        email_enabled=pref.email_enabled,
    )


# --- One-click email unsubscribe --------------------------------------------


@router.get("/unsubscribe", response_class=HTMLResponse, include_in_schema=False)
def unsubscribe(token: str, db: Session = Depends(get_db)):
    """Public, unauthenticated landing page for the "manage your email preferences" link in every outgoing
    email's footer (`services/notifications.py::_unsubscribe_url`, `security.create_email_unsubscribe_token`).

    Deliberately narrow: the token can only set `User.email_digest_mode = DigestMode.NONE`, the field a
    logged-in user sets from the Preferences page (`PUT /auth/me`), so a one-click unsubscribe is the same
    state, not a parallel flag, and no other account state is reachable. This is a narrow exception to
    authenticated-request handling (as the "shared UI chrome" carve-out in
    `docs/soc2/policies/access-control-policy.md`): a recipient clicking a mail link has no session.

    Every use, successful or a rejected, expired or tampered token, writes an audit entry
    (`services/audit.py::log_event`) per `docs/soc2/policies/system-operations-monitoring-and-logging-policy.md`.
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


@router.get("/{notification_id}", response_model=NotificationDetailOut)
def get_notification(notification_id: UUID, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """One of the caller's notifications, with whether its subject is still reachable.

    This is the page every notification link opens (the bell, the list, the email), so the browser can open the
    subject, or show the full message when no page applies or the person's access to it has ended. Another
    person's notification, and one a scoped credential may not see, answer as absent. Registered after the fixed
    paths above so `preferences` and `unsubscribe` are not read as an id.

    Args:
        notification_id: The notification.

    Returns:
        The notification and `subject_available`.

    Raises:
        HTTPException: 404 when it is not the caller's, or the credential's scope excludes its project.
    """
    notification = db.get(Notification, notification_id)
    if notification is None or notification.user_id != current_user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Notification not found.")
    allowed_orgs, allowed_projects = db.info.get("pat_allowed_org_ids"), db.info.get("pat_allowed_project_ids")
    if allowed_orgs is not None or allowed_projects is not None or "module_frame_project_id" in db.info:
        reachable = restrict_to_session_scope(db, {notification.project_id} if notification.project_id else set())
        if notification.project_id is None or notification.project_id not in reachable:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Notification not found.")
    detail = NotificationDetailOut.model_validate(_out(notification).model_dump())
    detail.subject_available = subject_available(db, current_user.id, notification)
    return detail
