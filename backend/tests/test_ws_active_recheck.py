"""Tests for `routers.ws._user_still_active` (SOC 2 access-control hardening
pass): the periodic WebSocket deactivation recheck. The full timed
WebSocket loop itself isn't exercised here (would require waiting out
`_EXPIRY_CHECK_INTERVAL_SECONDS` or mocking asyncio timing) — this covers
the DB-backed check the loop calls every interval."""

import uuid

from app.database import SessionLocal
from app.models.user import User
from app.routers.ws import _user_still_active


def test_user_still_active_true_for_active_user():
    db = SessionLocal()
    try:
        user = User(
            id=uuid.uuid4(), email=f"ws-active-{uuid.uuid4()}@example.com", display_name="WS Active",
            auth_backend="native", password_hash="not-a-real-hash", is_active=True,
        )
        db.add(user)
        db.commit()
        assert _user_still_active(user.id) is True
    finally:
        db.rollback()
        db.close()


def test_user_still_active_false_once_deactivated():
    db = SessionLocal()
    try:
        user = User(
            id=uuid.uuid4(), email=f"ws-inactive-{uuid.uuid4()}@example.com", display_name="WS Inactive",
            auth_backend="native", password_hash="not-a-real-hash", is_active=True,
        )
        db.add(user)
        db.commit()
        user.is_active = False
        db.commit()
        assert _user_still_active(user.id) is False
    finally:
        db.rollback()
        db.close()


def test_user_still_active_false_for_unknown_user():
    assert _user_still_active(uuid.uuid4()) is False
