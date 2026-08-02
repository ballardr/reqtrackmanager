"""
Module: services.notifications

Creates in-app notifications (C-N-01, C-N-02) and, depending on the
recipient's per-type preference (C-N-04) and email digest mode (C-N-05),
sends them by email immediately or queues them for the daily digest batch.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.notification import DigestMode, Notification, NotificationPreference, NotificationType
from app.models.user import User
from app.services.email import send_email, send_email_async

DIGEST_INTERVAL_SECONDS = 24 * 60 * 60


def _get_preference(db: Session, user_id: UUID, notification_type: NotificationType) -> NotificationPreference | None:
    """Returns a user's stored UI/email preference for one notification
    type, or None if they've never set one (C-N-04)."""
    return db.scalar(
        select(NotificationPreference).where(
            NotificationPreference.user_id == user_id, NotificationPreference.type == notification_type
        )
    )


def notify(
    db: Session,
    user: User,
    *,
    notification_type: NotificationType,
    title: str,
    body: str = "",
    project_id: UUID | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
) -> Notification:
    """Creates a notification for a user and sends it by email if appropriate.

    Args:
        db: An active database session (the row is added but the caller
            commits, consistent with the rest of the service layer).
        user: The recipient.
        notification_type: Which event this is (C-N-01).
        title: Short notification title, shown in the UI and as the email subject.
        body: Longer description, shown in the UI and email body.
        project_id / entity_type / entity_id: Optional context for deep-linking.

    Returns:
        The created Notification.
    """
    pref = _get_preference(db, user.id, notification_type)
    ui_enabled = pref.ui_enabled if pref else True
    email_enabled = pref.email_enabled if pref else True

    notification = Notification(
        user_id=user.id,
        type=notification_type,
        title=title,
        body=body,
        project_id=project_id,
        entity_type=entity_type,
        entity_id=entity_id,
        created_at=datetime.now(UTC),
    )
    if not ui_enabled:
        # Still recorded (so read-state / digest bookkeeping stays simple),
        # but hidden from the UI list via a null read_at is irrelevant here;
        # the notifications endpoint filters by preference at query time.
        pass
    db.add(notification)

    if email_enabled and user.email_digest_mode == DigestMode.INSTANT:
        try:
            send_email(user.email, title, body or title)
            notification.emailed_at = datetime.now(UTC)
        except Exception:  # noqa: BLE001 - never let email delivery break the triggering request
            pass

    return notification


async def run_digest_loop() -> None:
    """Runs forever, sending the daily digest batch on a fixed interval.

    Consistent with the disk-usage monitor (services/disk_monitor.py): an
    in-process asyncio background task rather than a separate worker
    service. This is a fixed-interval loop rather than one aligned to a
    specific calendar time of day — adequate for this deployment model;
    calendar-aligned scheduling would be a natural follow-up once a real
    task scheduler is introduced.
    """
    import asyncio
    import logging

    from app.database import SessionLocal

    logger = logging.getLogger(__name__)
    while True:
        await asyncio.sleep(DIGEST_INTERVAL_SECONDS)
        db = SessionLocal()
        try:
            await send_daily_digests(db)
        except Exception:  # noqa: BLE001 - a digest failure must never crash the app
            logger.exception("Daily digest run failed")
        finally:
            db.close()


async def send_daily_digests(db: Session) -> None:
    """Batches un-emailed notifications for users on daily digest mode into one email each (C-N-05)."""
    users = db.scalars(select(User).where(User.email_digest_mode == DigestMode.DAILY)).all()
    for user in users:
        pending = db.scalars(
            select(Notification).where(Notification.user_id == user.id, Notification.emailed_at.is_(None))
        ).all()
        if not pending:
            continue
        body = "\n".join(f"- {n.title}: {n.body}" for n in pending)
        await send_email_async(user.email, f"ReqTrackManager: {len(pending)} new notifications", body)
        now = datetime.now(UTC)
        for n in pending:
            n.emailed_at = now
    db.commit()
