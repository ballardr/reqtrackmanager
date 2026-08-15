"""Tests for the daily email digest batching (C-N-05). Email delivery
itself is mocked here (verified for real against MailHog in
docs/decisions.md's manual verification) so this only exercises the
batching/bookkeeping logic in isolation from network/SMTP availability."""

from unittest.mock import AsyncMock, patch

import pytest

from app.database import SessionLocal
from app.models.notification import DigestMode
from app.models.user import User
from app.services import notifications
from tests.conftest import auth_headers


@pytest.mark.asyncio
async def test_daily_digest_batches_notifications_and_marks_emailed(client, admin_token):
    client.patch("/api/v1/auth/me/preferences", json={"email_digest_mode": "daily"}, headers=auth_headers(admin_token))

    # Two password changes -> two notifications, both should be un-emailed
    # (instant delivery only applies to "instant" mode).
    client.post(
        "/api/v1/auth/change-password",
        json={"current_password": "ChangeMe123!", "new_password": "Second123!"},
        headers=auth_headers(admin_token),
    )
    from tests.conftest import login

    token2 = login(client, "admin@example.com", "Second123!")
    client.post(
        "/api/v1/auth/change-password",
        json={"current_password": "Second123!", "new_password": "Third123!"},
        headers=auth_headers(token2),
    )

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == "admin@example.com").one()
        assert user.email_digest_mode == DigestMode.DAILY

        with patch.object(notifications, "send_email_async", new=AsyncMock()) as mock_send:
            await notifications.send_daily_digests(db)
            assert mock_send.await_count == 1
            call_args = mock_send.await_args
            assert call_args.args[0] == "admin@example.com"
            # The digest is a real rendered HTML email (services/email_templates.py),
            # not the old plain-text-only body, and lists both batched notifications.
            html_body = call_args.kwargs["html_body"]
            assert "<html" in html_body.lower()
            assert html_body.count("Your password was changed") == 2

        db.refresh(user)
        from sqlalchemy import select

        from app.models.notification import Notification

        pending = db.scalars(
            select(Notification).where(Notification.user_id == user.id, Notification.emailed_at.is_(None))
        ).all()
        assert pending == []

        # Running again with nothing new pending should not send another email.
        with patch.object(notifications, "send_email_async", new=AsyncMock()) as mock_send_again:
            await notifications.send_daily_digests(db)
            assert mock_send_again.await_count == 0
    finally:
        db.close()
