"""
Module: routers.notifications

In-app notification centre (C-N-02) and per-type notification preferences
(C-N-04): list my notifications, mark read, and configure UI/email delivery
per notification type.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models.notification import Notification, NotificationPreference, NotificationType
from app.models.user import User
from app.schemas.notification import NotificationOut, NotificationPreferenceOut, NotificationPreferenceUpdate

router = APIRouter(prefix="/api/v1/notifications", tags=["notifications"])


@router.get("", response_model=list[NotificationOut])
def list_notifications(
    unread_only: bool = False, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    query = select(Notification).where(Notification.user_id == current_user.id)
    if unread_only:
        query = query.where(Notification.read_at.is_(None))
    return db.scalars(query.order_by(Notification.created_at.desc())).all()


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
