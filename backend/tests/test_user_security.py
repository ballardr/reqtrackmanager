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


def test_password_change_invalidates_the_old_token(client, admin_token):
    """Security regression: stateless JWTs have no revocation by default, so
    without an explicit check, a token stolen before a password change would
    keep working for its full remaining lifetime even after the legitimate
    user "locks out" that session by changing their password."""
    # The token is valid before the change.
    assert client.get("/api/v1/auth/me", headers=auth_headers(admin_token)).status_code == 200

    resp = client.post(
        "/api/v1/auth/change-password",
        json={"current_password": "ChangeMe123!", "new_password": "NewPassword123!"},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 204

    # The pre-change token — including this exact request's own token — no
    # longer authenticates anything.
    assert client.get("/api/v1/auth/me", headers=auth_headers(admin_token)).status_code == 401

    # A fresh login with the new password gets a token that works fine.
    new_token = login(client, "admin@example.com", "NewPassword123!")
    assert client.get("/api/v1/auth/me", headers=auth_headers(new_token)).status_code == 200


def test_2fa_disable_invalidates_the_old_token(client, admin_token):
    enroll = client.post("/api/v1/auth/2fa/enroll", headers=auth_headers(admin_token))
    secret = enroll.json()["secret"]
    code = pyotp.TOTP(secret).now()
    client.post("/api/v1/auth/2fa/confirm", json={"code": code}, headers=auth_headers(admin_token))

    assert client.get("/api/v1/auth/me", headers=auth_headers(admin_token)).status_code == 200

    disable_code = pyotp.TOTP(secret).now()
    resp = client.post("/api/v1/auth/2fa/disable", json={"code": disable_code}, headers=auth_headers(admin_token))
    assert resp.status_code == 204

    assert client.get("/api/v1/auth/me", headers=auth_headers(admin_token)).status_code == 401


def test_login_error_does_not_distinguish_deactivated_from_wrong_password(client, admin_token, org_id):
    """Security regression: the login error for a deactivated account used
    to be a distinct message ("This account is deactivated.") returned
    *before* password verification even ran, letting an attacker enumerate
    which emails are registered-but-deactivated accounts without knowing
    the password at all. Both the message and the code path must now be
    indistinguishable from an ordinary wrong-password attempt."""
    from tests.conftest import create_org_user

    user_id = create_org_user(client, admin_token, org_id, "soon_deactivated@example.com", role="member")
    client.post(f"/api/v1/orgs/{org_id}/users/{user_id}/deactivate", headers=auth_headers(admin_token))

    wrong_password_resp = client.post(
        "/api/v1/auth/login", json={"email": "admin@example.com", "password": "not-the-right-password"}
    )
    deactivated_correct_password_resp = client.post(
        "/api/v1/auth/login", json={"email": "soon_deactivated@example.com", "password": "Password123!"}
    )
    nonexistent_resp = client.post(
        "/api/v1/auth/login", json={"email": "no-such-user@example.com", "password": "whatever"}
    )

    for resp in (wrong_password_resp, deactivated_correct_password_resp, nonexistent_resp):
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Invalid email or password."


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
