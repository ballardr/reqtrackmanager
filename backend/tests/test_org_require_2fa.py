"""Tests for the org-level `require_2fa` setting: blocks every org/project-
scoped request for a member without `User.is_2fa_enabled`, including the
org's own admins — same bluntness as `is_active` (see
test_org_lifecycle.py) — but with a self-service way out, since enrolling
in 2FA isn't itself an org-scoped action.
"""

import pyotp

from tests.conftest import auth_headers, create_org_admin_in, create_project


def _set_require_2fa(client, token, org_id, value: bool):
    resp = client.put(
        f"/api/v1/orgs/{org_id}/advanced-settings",
        json={"require_2fa": value},
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _enroll_2fa(client, token) -> None:
    enroll = client.post("/api/v1/auth/2fa/enroll", headers=auth_headers(token))
    assert enroll.status_code == 200, enroll.text
    secret = enroll.json()["secret"]
    code = pyotp.TOTP(secret).now()
    confirm = client.post("/api/v1/auth/2fa/confirm", json={"code": code}, headers=auth_headers(token))
    assert confirm.status_code == 204, confirm.text


def test_require_2fa_blocks_org_and_project_access_including_the_orgs_own_admin(client, admin_token):
    org, org_admin_token = create_org_admin_in(client, admin_token, "Require 2FA Org")
    project = create_project(client, org_admin_token, org["id"])
    _set_require_2fa(client, org_admin_token, org["id"], True)

    resp = client.get(f"/api/v1/orgs/{org['id']}/groups", headers=auth_headers(org_admin_token))
    assert resp.status_code == 403
    assert "two-factor" in resp.json()["detail"].lower()

    resp = client.get(f"/api/v1/projects/{project['id']}", headers=auth_headers(org_admin_token))
    assert resp.status_code == 403
    assert "two-factor" in resp.json()["detail"].lower()


def test_require_2fa_self_service_unblock(client, admin_token):
    org, org_admin_token = create_org_admin_in(client, admin_token, "Require 2FA Self Service Org")
    _set_require_2fa(client, org_admin_token, org["id"], True)

    resp = client.get(f"/api/v1/orgs/{org['id']}/groups", headers=auth_headers(org_admin_token))
    assert resp.status_code == 403

    # No admin intervention needed — the blocked user can enrol themselves,
    # since /auth/2fa/enroll and /confirm aren't org-scoped.
    _enroll_2fa(client, org_admin_token)

    resp = client.get(f"/api/v1/orgs/{org['id']}/groups", headers=auth_headers(org_admin_token))
    assert resp.status_code == 200


def test_require_2fa_does_not_block_a_user_who_already_has_2fa(client, admin_token):
    org, org_admin_token = create_org_admin_in(client, admin_token, "Require 2FA Preenrolled Org")
    _enroll_2fa(client, org_admin_token)
    _set_require_2fa(client, org_admin_token, org["id"], True)

    resp = client.get(f"/api/v1/orgs/{org['id']}/groups", headers=auth_headers(org_admin_token))
    assert resp.status_code == 200


def test_require_2fa_off_by_default(client, admin_token):
    org, org_admin_token = create_org_admin_in(client, admin_token, "Default 2FA Org")
    resp = client.get(f"/api/v1/orgs/{org['id']}/groups", headers=auth_headers(org_admin_token))
    assert resp.status_code == 200
