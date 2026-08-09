"""Tests for public self-signup (`POST /api/v1/auth/signup`) and the
server-wide `signup_mode` setting (`GET`/`PUT /api/v1/system/signup-config`)."""

from tests.conftest import auth_headers


def _set_signup_mode(client, admin_token, mode):
    resp = client.put(
        "/api/v1/system/signup-config", json={"signup_mode": mode}, headers=auth_headers(admin_token)
    )
    assert resp.status_code == 200, resp.text


def test_signup_config_is_public_and_defaults_to_disabled(client):
    resp = client.get("/api/v1/system/signup-config")
    assert resp.status_code == 200
    assert resp.json()["signup_mode"] == "disabled"


def test_signup_rejected_when_mode_is_disabled(client):
    resp = client.post(
        "/api/v1/auth/signup",
        json={"email": "nope@example.com", "password": "Password123!", "display_name": "Nope"},
    )
    assert resp.status_code == 403


def test_signup_succeeds_with_no_org_when_always_on(client, admin_token):
    _set_signup_mode(client, admin_token, "always_on")
    resp = client.post(
        "/api/v1/auth/signup",
        json={"email": "opensignup@example.com", "password": "Password123!", "display_name": "Open Signup"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["user"]["email"] == "opensignup@example.com"
    assert "access_token" in body

    # Logging in again afterward confirms the account was really created,
    # not just returned as a one-off token.
    login_resp = client.post(
        "/api/v1/auth/login", json={"email": "opensignup@example.com", "password": "Password123!"}
    )
    assert login_resp.status_code == 200


def test_signup_rejects_duplicate_email(client, admin_token):
    _set_signup_mode(client, admin_token, "always_on")
    payload = {"email": "dupe@example.com", "password": "Password123!", "display_name": "Dupe"}
    assert client.post("/api/v1/auth/signup", json=payload).status_code == 201
    assert client.post("/api/v1/auth/signup", json=payload).status_code == 409


def test_org_specified_signup_requires_domain_match(client, admin_token):
    _set_signup_mode(client, admin_token, "org_specified")
    resp = client.post(
        "/api/v1/auth/signup",
        json={"email": "nomatch@unconfigured.example.com", "password": "Password123!", "display_name": "No Match"},
    )
    assert resp.status_code == 400


def test_org_specified_signup_joins_matching_org_as_member(client, admin_token):
    org = client.post("/api/v1/orgs", json={"name": "DomainOrg"}, headers=auth_headers(admin_token)).json()
    client.post(
        f"/api/v1/orgs/{org['id']}/users",
        json={"email": "domainorg_admin@example.com", "display_name": "Domain Org Admin",
              "password": "Password123!", "role": "org_admin"},
        headers=auth_headers(admin_token),
    )
    org_admin_login = client.post(
        "/api/v1/auth/login", json={"email": "domainorg_admin@example.com", "password": "Password123!"}
    ).json()
    org_admin_token = org_admin_login["access_token"]
    resp = client.put(
        f"/api/v1/orgs/{org['id']}/advanced-settings",
        json={"allow_self_signup": True, "auto_accept_email_domain": "domainorg.example.com"},
        headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 200, resp.text

    _set_signup_mode(client, admin_token, "org_specified")
    resp = client.post(
        "/api/v1/auth/signup",
        json={"email": "newbie@domainorg.example.com", "password": "Password123!", "display_name": "Newbie"},
    )
    assert resp.status_code == 201, resp.text
    new_user_token = resp.json()["access_token"]

    orgs = client.get("/api/v1/orgs", headers=auth_headers(new_user_token)).json()
    assert any(o["id"] == org["id"] for o in orgs)


def test_org_specified_signup_ignores_orgs_that_have_not_opted_in(client, admin_token):
    """A domain being configured on an org that hasn't set allow_self_signup
    must never be sufficient to join it — domain match alone is not
    authorization."""
    org = client.post("/api/v1/orgs", json={"name": "NotOptedInOrg"}, headers=auth_headers(admin_token)).json()
    client.post(
        f"/api/v1/orgs/{org['id']}/users",
        json={"email": "notoptedin_admin@example.com", "display_name": "Admin",
              "password": "Password123!", "role": "org_admin"},
        headers=auth_headers(admin_token),
    )
    org_admin_token = client.post(
        "/api/v1/auth/login", json={"email": "notoptedin_admin@example.com", "password": "Password123!"}
    ).json()["access_token"]
    # Sets the domain but leaves allow_self_signup at its default False.
    client.put(
        f"/api/v1/orgs/{org['id']}/advanced-settings",
        json={"auto_accept_email_domain": "notoptedin.example.com"},
        headers=auth_headers(org_admin_token),
    )

    _set_signup_mode(client, admin_token, "org_specified")
    resp = client.post(
        "/api/v1/auth/signup",
        json={"email": "someone@notoptedin.example.com", "password": "Password123!", "display_name": "Someone"},
    )
    assert resp.status_code == 400
