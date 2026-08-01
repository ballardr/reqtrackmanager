"""Tests for Pelion (v2) user profile & security features: self-service
profile edits, org-admin display-name locking (C-U-16), and TOTP 2FA
(C-U-14)."""

import pyotp

from tests.conftest import auth_headers, login


def test_user_can_update_pronouns_and_theme(client, admin_token):
    resp = client.patch(
        "/api/v1/auth/me/preferences",
        json={"pronouns": "they/them", "theme_preference": "dark"},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["pronouns"] == "they/them"
    assert body["theme_preference"] == "dark"


def test_display_name_change_blocked_once_locked(client, admin_token, org_id):
    from tests.conftest import create_org_user

    user_id = create_org_user(client, admin_token, org_id, "locked@example.com", role="member")
    token = login(client, "locked@example.com", "Password123!")

    resp = client.patch(
        "/api/v1/auth/me/preferences", json={"display_name": "New Name"}, headers=auth_headers(token)
    )
    assert resp.status_code == 200
    assert resp.json()["display_name"] == "New Name"

    from app.database import SessionLocal
    from app.models.user import User

    db = SessionLocal()
    try:
        user = db.get(User, __import__("uuid").UUID(user_id))
        user.display_name_locked = True
        db.commit()
    finally:
        db.close()

    resp = client.patch(
        "/api/v1/auth/me/preferences", json={"display_name": "Blocked Name"}, headers=auth_headers(token)
    )
    assert resp.status_code == 403


def test_change_password_requires_current_password(client, admin_token):
    resp = client.post(
        "/api/v1/auth/change-password",
        json={"current_password": "wrong", "new_password": "NewPassword123!"},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 401

    resp = client.post(
        "/api/v1/auth/change-password",
        json={"current_password": "ChangeMe123!", "new_password": "NewPassword123!"},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 204

    # Old password no longer works; new one does.
    resp = client.post(
        "/api/v1/auth/login", json={"email": "admin@example.com", "password": "ChangeMe123!"}
    )
    assert resp.status_code == 401
    resp = client.post(
        "/api/v1/auth/login", json={"email": "admin@example.com", "password": "NewPassword123!"}
    )
    assert resp.status_code == 200


def test_2fa_enroll_confirm_and_login_flow(client, admin_token):
    enroll = client.post("/api/v1/auth/2fa/enroll", headers=auth_headers(admin_token))
    assert enroll.status_code == 200
    secret = enroll.json()["secret"]
    assert enroll.json()["qr_code_png_base64"]

    code = pyotp.TOTP(secret).now()
    confirm = client.post("/api/v1/auth/2fa/confirm", json={"code": code}, headers=auth_headers(admin_token))
    assert confirm.status_code == 204

    # Plain login now returns a 2FA challenge, not a token.
    resp = client.post(
        "/api/v1/auth/login", json={"email": "admin@example.com", "password": "ChangeMe123!"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["requires_2fa"] is True
    challenge_token = body["challenge_token"]

    # The challenge token alone must not work as a real access token.
    resp = client.get("/api/v1/auth/me", headers=auth_headers(challenge_token))
    assert resp.status_code == 401

    # Wrong TOTP code is rejected.
    resp = client.post(
        "/api/v1/auth/2fa/verify", json={"challenge_token": challenge_token, "code": "000000"}
    )
    assert resp.status_code == 401

    # Correct code completes login.
    resp = client.post(
        "/api/v1/auth/2fa/verify",
        json={"challenge_token": challenge_token, "code": pyotp.TOTP(secret).now()},
    )
    assert resp.status_code == 200
    real_token = resp.json()["access_token"]
    resp = client.get("/api/v1/auth/me", headers=auth_headers(real_token))
    assert resp.status_code == 200

    # Disabling requires a valid code.
    resp = client.post("/api/v1/auth/2fa/disable", json={"code": "000000"}, headers=auth_headers(real_token))
    assert resp.status_code == 400
    resp = client.post(
        "/api/v1/auth/2fa/disable", json={"code": pyotp.TOTP(secret).now()}, headers=auth_headers(real_token)
    )
    assert resp.status_code == 204
