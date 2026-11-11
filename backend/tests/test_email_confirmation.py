"""Public sign-up must confirm its email address before the account can sign in (access control Known Gap 4)."""

from __future__ import annotations

import re
from unittest.mock import Mock, patch

import pytest

from app.config import get_settings
from app.services import email_confirmation
from tests.conftest import auth_headers, login

LINK = re.compile(r"/confirm-email#token=([\w-]+)")
SIGNUP = {"email": "newcomer@example.com", "password": "Own-Choice-Password-3!", "display_name": "Newcomer"}


@pytest.fixture
def required(monkeypatch, client, admin_token):
    monkeypatch.setattr(get_settings(), "require_email_confirmation", True)
    assert client.put(
        "/api/v1/system/signup-config", json={"signup_mode": "always_on"}, headers=auth_headers(admin_token)
    ).status_code == 200


@pytest.fixture
def mail():
    with patch.object(email_confirmation, "send_email", new=Mock()) as sent:
        yield sent


def _token(mail_mock) -> str:
    match = LINK.search(mail_mock.call_args.args[2])
    assert match, mail_mock.call_args.args[2]
    return match.group(1)


def test_a_public_sign_up_gets_no_session_until_the_link_is_opened(client, required, mail):
    response = client.post("/api/v1/auth/signup", json=SIGNUP)
    assert response.status_code == 202
    assert response.json()["confirmation_required"] is True and "access_token" not in response.json()

    blocked = client.post("/api/v1/auth/login", json={"email": SIGNUP["email"], "password": SIGNUP["password"]})
    assert blocked.status_code == 403 and "Confirm your email address" in blocked.json()["detail"]
    wrong = client.post("/api/v1/auth/login", json={"email": SIGNUP["email"], "password": "Another-Password-4!"})
    assert wrong.status_code == 401  # only a correct password learns that the account is waiting

    assert client.post("/api/v1/auth/confirm-email", json={"token": _token(mail)}).status_code == 204
    assert login(client, SIGNUP["email"], SIGNUP["password"])


def test_a_link_works_once_and_a_wrong_one_is_refused(client, required, mail):
    client.post("/api/v1/auth/signup", json=SIGNUP)
    token = _token(mail)
    assert client.post("/api/v1/auth/confirm-email", json={"token": token}).status_code == 204
    again = client.post("/api/v1/auth/confirm-email", json={"token": token})
    assert again.status_code == 400 and "invalid or has expired" in again.json()["detail"]
    assert client.post("/api/v1/auth/confirm-email", json={"token": "x" * 40}).status_code == 400


def test_a_confirmation_link_cannot_set_a_password(client, required, mail):
    client.post("/api/v1/auth/signup", json=SIGNUP)
    token = _token(mail)
    refused = client.post("/api/v1/auth/reset-password", json={"token": token, "new_password": "Taken-Over-Password-5!"})
    assert refused.status_code == 400
    assert client.post("/api/v1/auth/login", json={"email": SIGNUP["email"], "password": "Taken-Over-Password-5!"}).status_code == 401


def test_resend_answers_the_same_for_every_address_and_sends_only_to_a_waiting_account(client, required, mail):
    client.post("/api/v1/auth/signup", json=SIGNUP)
    mail.reset_mock()
    for address in (SIGNUP["email"], "nobody@example.com", "admin@example.com"):
        answer = client.post("/api/v1/auth/resend-confirmation", json={"email": address})
        assert answer.status_code == 202
    assert mail.call_count == 0  # the first link was just sent: the cooldown holds


def test_an_invited_person_is_not_asked_to_confirm(client, admin_token, required, mail):
    """The invitation link went to the address, which is the proof a confirmation link would give."""
    import uuid
    from datetime import UTC, datetime, timedelta

    from app.database import SessionLocal
    from app.models.organization import PendingInvite

    org_id = client.get("/api/v1/orgs", headers=auth_headers(admin_token)).json()[0]["id"]
    admin_id = client.get("/api/v1/auth/me", headers=auth_headers(admin_token)).json()["id"]
    db = SessionLocal()
    try:
        db.add(PendingInvite(
            email=SIGNUP["email"], organization_id=uuid.UUID(org_id), invited_by=uuid.UUID(admin_id), token="invite-token-" + "x" * 30,
            expires_at=datetime.now(UTC) + timedelta(days=1),
        ))
        db.commit()
    finally:
        db.close()
    response = client.post("/api/v1/auth/signup", json={**SIGNUP, "invite_token": "invite-token-" + "x" * 30})
    assert response.status_code == 201 and response.json()["access_token"]
    assert mail.call_count == 0
