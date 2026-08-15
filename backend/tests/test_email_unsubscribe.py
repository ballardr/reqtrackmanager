"""Tests for the one-click email-unsubscribe link (`GET
/notifications/unsubscribe`, `security.create_email_unsubscribe_token`/
`decode_email_unsubscribe_token`): a valid token flips `User.
email_digest_mode` to `NONE` — the same field the logged-in Preferences
page controls — and every use, successful or rejected, is written to the
audit trail (SOC 2 logging policy; see docs/decisions.md)."""

from datetime import UTC, datetime, timedelta

from jose import jwt
from sqlalchemy import select

from app.config import get_settings
from app.database import SessionLocal
from app.models.audit import AuditEvent
from app.models.notification import DigestMode
from app.models.user import User
from app.security import create_email_unsubscribe_token
from tests.conftest import auth_headers, create_org_user

settings = get_settings()


def _digest_mode(user_id: str) -> DigestMode:
    db = SessionLocal()
    try:
        return db.get(User, user_id).email_digest_mode
    finally:
        db.close()


def _audit_events(action: str) -> list[AuditEvent]:
    db = SessionLocal()
    try:
        return list(db.scalars(select(AuditEvent).where(AuditEvent.action == action)))
    finally:
        db.close()


def test_valid_token_disables_email_and_updates_the_same_field_as_preferences(client, admin_token, org_id):
    user_id = create_org_user(client, admin_token, org_id, "unsub_target@example.com")
    assert _digest_mode(user_id) == DigestMode.INSTANT

    token = create_email_unsubscribe_token(user_id)
    resp = client.get(f"/api/v1/notifications/unsubscribe?token={token}")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "unsubscribed" in resp.text.lower()

    assert _digest_mode(user_id) == DigestMode.NONE

    events = _audit_events("email_unsubscribed_via_link")
    assert any(str(e.entity_id) == user_id for e in events)


def test_unsubscribe_updates_the_field_a_logged_in_user_would_edit_themselves(client, admin_token, org_id):
    """Proves the one-click link and `PUT /auth/me` (the Preferences page)
    are the same state, not a parallel flag."""
    email = "unsub_selfcheck@example.com"
    user_id = create_org_user(client, admin_token, org_id, email)
    token = create_email_unsubscribe_token(user_id)
    client.get(f"/api/v1/notifications/unsubscribe?token={token}")

    from tests.conftest import login

    user_token = login(client, email, "Password123!")
    me = client.get("/api/v1/auth/me", headers=auth_headers(user_token))
    assert me.status_code == 200
    assert me.json()["email_digest_mode"] == "none"


def test_repeated_use_is_idempotent(client, admin_token, org_id):
    user_id = create_org_user(client, admin_token, org_id, "unsub_repeat@example.com")
    token = create_email_unsubscribe_token(user_id)
    for _ in range(2):
        resp = client.get(f"/api/v1/notifications/unsubscribe?token={token}")
        assert resp.status_code == 200
    assert _digest_mode(user_id) == DigestMode.NONE
    assert len(_audit_events("email_unsubscribed_via_link")) >= 2


def test_garbage_token_rejected_and_logged(client, admin_token, org_id):
    user_id = create_org_user(client, admin_token, org_id, "unsub_garbage@example.com")
    assert _digest_mode(user_id) == DigestMode.INSTANT

    resp = client.get("/api/v1/notifications/unsubscribe?token=not-a-real-token")
    assert resp.status_code == 200
    assert "invalid" in resp.text.lower() or "expired" in resp.text.lower()

    assert _digest_mode(user_id) == DigestMode.INSTANT
    assert len(_audit_events("email_unsubscribe_link_rejected")) >= 1


def test_expired_token_is_rejected(client, admin_token, org_id):
    user_id = create_org_user(client, admin_token, org_id, "unsub_expired@example.com")
    expired_payload = {
        "sub": user_id, "exp": datetime.now(UTC) - timedelta(days=1), "purpose": "email_unsubscribe",
    }
    expired_token = jwt.encode(expired_payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)

    resp = client.get(f"/api/v1/notifications/unsubscribe?token={expired_token}")
    assert resp.status_code == 200
    assert _digest_mode(user_id) == DigestMode.INSTANT


def test_token_with_wrong_purpose_is_rejected(client, admin_token, org_id):
    """A session access token (or any other purpose-tagged token) must not
    be usable here — only a genuine `purpose: "email_unsubscribe"` token."""
    user_id = create_org_user(client, admin_token, org_id, "unsub_wrongpurpose@example.com")
    not_an_unsubscribe_token = jwt.encode(
        {"sub": user_id, "exp": datetime.now(UTC) + timedelta(days=1), "purpose": "access", "tv": 0},
        settings.jwt_secret, algorithm=settings.jwt_algorithm,
    )
    resp = client.get(f"/api/v1/notifications/unsubscribe?token={not_an_unsubscribe_token}")
    assert resp.status_code == 200
    assert _digest_mode(user_id) == DigestMode.INSTANT


def test_tampered_signature_is_rejected(client, admin_token, org_id):
    user_id = create_org_user(client, admin_token, org_id, "unsub_tampered@example.com")
    token = create_email_unsubscribe_token(user_id)
    tampered = token[:-4] + ("AAAA" if not token.endswith("AAAA") else "BBBB")

    resp = client.get(f"/api/v1/notifications/unsubscribe?token={tampered}")
    assert resp.status_code == 200
    assert _digest_mode(user_id) == DigestMode.INSTANT


def test_unknown_user_id_in_an_otherwise_valid_token_is_rejected(client):
    """A correctly-signed, unexpired token whose `sub` doesn't match any
    real user (e.g. the account was deleted) must fail closed, not 500."""
    token = create_email_unsubscribe_token("00000000-0000-0000-0000-000000000000")
    resp = client.get(f"/api/v1/notifications/unsubscribe?token={token}")
    assert resp.status_code == 200
    assert "invalid" in resp.text.lower() or "expired" in resp.text.lower()
