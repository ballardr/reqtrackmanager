"""Tests for `routers.ws._user_session_still_valid` (SOC 2 access-control
hardening pass, extended by a later hardening review to also cover
`token_version` — see test_websocket_security.py for the token_version-
specific regression coverage): the periodic WebSocket deactivation/
revocation recheck. The full timed WebSocket loop itself isn't exercised
here (would require waiting out `_EXPIRY_CHECK_INTERVAL_SECONDS` or mocking
asyncio timing) — this covers the DB-backed check the loop calls every
interval."""

import uuid

from app.database import SessionLocal
from app.models.user import User
from app.routers.ws import _user_session_still_valid


def test_user_session_still_valid_true_for_active_user_with_matching_token_version():
    db = SessionLocal()
    try:
        user = User(
            id=uuid.uuid4(), email=f"ws-active-{uuid.uuid4()}@example.com", display_name="WS Active",
            auth_backend="native", password_hash="not-a-real-hash", is_active=True,
        )
        db.add(user)
        db.commit()
        assert _user_session_still_valid(user.id, token_version=user.token_version, organization_id=None) is True
    finally:
        db.rollback()
        db.close()


def test_user_session_still_valid_false_once_deactivated():
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
        assert _user_session_still_valid(user.id, token_version=user.token_version, organization_id=None) is False
    finally:
        db.rollback()
        db.close()


def test_user_session_still_valid_false_for_unknown_user():
    assert _user_session_still_valid(uuid.uuid4(), token_version=0, organization_id=None) is False
