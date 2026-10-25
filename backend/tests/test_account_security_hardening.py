"""Tests for the account-security endpoints' hardening: a Personal Access Token cannot manage credentials, an
active second factor cannot be replaced without disabling it, and the enrol/disable step is throttled.
"""

import pyotp

from tests.conftest import auth_headers


def _enable_2fa(client, token: str) -> str:
    """Enrols and confirms a TOTP second factor for the caller; returns its secret."""
    headers = auth_headers(token)
    secret = client.post("/api/v1/auth/2fa/enroll", headers=headers).json()["secret"]
    confirmed = client.post("/api/v1/auth/2fa/status", json={"action": "confirm", "code": pyotp.TOTP(secret).now()}, headers=headers)
    assert confirmed.status_code == 204, confirmed.text
    return secret


def test_a_pat_cannot_mint_another_pat_or_change_credentials(client, admin_token, org_id):
    """The token's scope and expiry mean nothing if it can mint a wider one or rewrite the second factor."""
    created = client.post(
        "/api/v1/me/pats", json={"name": "narrow", "allowed_organization_ids": [org_id]}, headers=auth_headers(admin_token),
    )
    assert created.status_code == 201, created.text
    pat = auth_headers(created.json()["token"])

    assert client.post("/api/v1/me/pats", json={"name": "wide", "allowed_organization_ids": [org_id]}, headers=pat).status_code == 403
    assert client.get("/api/v1/me/pats", headers=pat).status_code == 403
    assert client.post("/api/v1/auth/2fa/enroll", headers=pat).status_code == 403
    assert client.post("/api/v1/auth/2fa/status", json={"action": "disable", "code": "000000"}, headers=pat).status_code == 403
    changed = client.post(
        "/api/v1/auth/change-password", json={"current_password": "ChangeMe123!", "new_password": "AnotherPass123!"}, headers=pat,
    )
    assert changed.status_code == 403
    # Ordinary use of the token is unaffected.
    assert client.get("/api/v1/auth/me", headers=pat).status_code == 200


def test_an_active_second_factor_cannot_be_replaced_then_disabled(client, admin_token):
    """Re-enrolling over an active factor is refused, so a held session cannot switch 2FA off using a secret it
    chose itself."""
    original = _enable_2fa(client, admin_token)
    headers = auth_headers(admin_token)

    assert client.post("/api/v1/auth/2fa/enroll", headers=headers).status_code == 409

    # The original secret is still the only one that works, and disabling needs it.
    wrong = client.post("/api/v1/auth/2fa/status", json={"action": "disable", "code": "000000"}, headers=headers)
    assert wrong.status_code == 400
    ok = client.post("/api/v1/auth/2fa/status", json={"action": "disable", "code": pyotp.TOTP(original).now()}, headers=headers)
    assert ok.status_code == 204


def test_disable_step_locks_out_after_repeated_wrong_codes(client, admin_token):
    """Guessing the six digits through the enrol/disable door counts against the same per-account lockout as
    `/2fa/verify`."""
    secret = _enable_2fa(client, admin_token)
    headers = auth_headers(admin_token)
    statuses = [
        client.post("/api/v1/auth/2fa/status", json={"action": "disable", "code": "000000"}, headers=headers).status_code
        for _ in range(5)
    ]
    assert statuses == [400, 400, 400, 400, 400]
    locked = client.post("/api/v1/auth/2fa/status", json={"action": "disable", "code": pyotp.TOTP(secret).now()}, headers=headers)
    assert locked.status_code == 429
