"""Tests for making `Organization.sso_only` a real backend control rather
than a UI-only hint (see docs/decisions.md's "Self-signup, invites, and
SSO" entry): native login rejection, the `update_sso_config` lockout
guard, and the account-creation guards that stop a brand-new
native-credentialed account from ever being created with no working way to
log in."""

from tests.conftest import auth_headers, create_org_admin_in, login


def _enable_sso_only(client, token, org_id, slug):
    resp = client.put(
        f"/api/v1/orgs/{org_id}/sso-config",
        json={"slug": slug, "sso_enabled": True, "sso_only": True},
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text


def test_native_login_rejected_when_only_org_is_sso_only(client):
    org, org_admin_token = create_org_admin_in(client, login(client, "admin@example.com", "ChangeMe123!"), "SsoOnlyOrg")
    _enable_sso_only(client, org_admin_token, org["id"], "sso-only-org")

    resp = client.post(
        "/api/v1/auth/login", json={"email": "ssoonlyorg_admin@example.com", "password": "Password123!"}
    )
    assert resp.status_code == 401
    assert "SSO" in resp.json()["detail"]


def test_native_login_still_works_with_a_second_non_sso_only_org(client, admin_token):
    org, org_admin_token = create_org_admin_in(client, admin_token, "SsoOnlyOrg2")
    _enable_sso_only(client, org_admin_token, org["id"], "sso-only-org-2")

    # Get the user's id via the (still-authenticated, sso_only doesn't block
    # already-org-scoped org-admin API access with a valid token — only the
    # native /login step itself) member listing, then grant them a role in a
    # second, non-sso_only org.
    users = client.get(f"/api/v1/orgs/{org['id']}/users", headers=auth_headers(org_admin_token)).json()
    user_id = next(u["user_id"] for u in users if u["email"] == "ssoonlyorg2_admin@example.com")

    # I-M-05: the server admin has no role of its own in a freshly created
    # org, so granting a role there requires that org's own admin.
    org_b, org_b_admin_token = create_org_admin_in(client, admin_token, "PlainOrg")
    resp = client.post(
        f"/api/v1/orgs/{org_b['id']}/users/{user_id}/roles",
        json={"user_id": user_id, "role": "member"}, headers=auth_headers(org_b_admin_token),
    )
    assert resp.status_code == 204, resp.text

    resp = client.post(
        "/api/v1/auth/login", json={"email": "ssoonlyorg2_admin@example.com", "password": "Password123!"}
    )
    assert resp.status_code == 200, resp.text


def test_update_sso_config_rejects_sso_only_without_sso_enabled(client, admin_token):
    org, org_admin_token = create_org_admin_in(client, admin_token, "LockoutGuardOrg")
    resp = client.put(
        f"/api/v1/orgs/{org['id']}/sso-config",
        json={"slug": "lockout-guard-org", "sso_enabled": False, "sso_only": True},
        headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 400


def test_update_sso_config_rejects_sso_only_while_self_signup_enabled(client, admin_token):
    org, org_admin_token = create_org_admin_in(client, admin_token, "SelfSignupGuardOrg")
    resp = client.put(
        f"/api/v1/orgs/{org['id']}/advanced-settings",
        json={"allow_self_signup": True, "auto_accept_email_domain": "guard.example.com"},
        headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 200, resp.text

    resp = client.put(
        f"/api/v1/orgs/{org['id']}/sso-config",
        json={"slug": "self-signup-guard-org", "sso_enabled": True, "sso_only": True},
        headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 400


def test_update_advanced_settings_rejects_self_signup_for_sso_only_org(client, admin_token):
    org, org_admin_token = create_org_admin_in(client, admin_token, "AlreadySsoOnlyOrg")
    _enable_sso_only(client, org_admin_token, org["id"], "already-sso-only-org")

    resp = client.put(
        f"/api/v1/orgs/{org['id']}/advanced-settings",
        json={"allow_self_signup": True, "auto_accept_email_domain": "already.example.com"},
        headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 400


def test_create_org_user_rejects_native_account_for_sso_only_org(client, admin_token):
    org, org_admin_token = create_org_admin_in(client, admin_token, "NoNativeOrg")
    _enable_sso_only(client, org_admin_token, org["id"], "no-native-org")

    resp = client.post(
        f"/api/v1/orgs/{org['id']}/users",
        json={"email": "new@nonative.example.com", "display_name": "New", "password": "Password123!", "role": "member"},
        headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 400
