"""Tests for the Massif (v3) broadened user-directory access-review filters
(C-A-13), including the authorization boundaries called out explicitly
during planning."""

from tests.conftest import auth_headers, create_org_admin_in, create_org_user, login


def test_plain_member_can_list_org_users_unfiltered(client, admin_token, org_id):
    """Existing behavior preserved: any org member can still see the
    unfiltered member directory."""
    create_org_user(client, admin_token, org_id, "plain_member@example.com", role="member")
    member_token = login(client, "plain_member@example.com", "Password123!")
    resp = client.get(f"/api/v1/orgs/{org_id}/users", headers=auth_headers(member_token))
    assert resp.status_code == 200


def test_plain_member_cannot_use_access_review_filters(client, admin_token, org_id):
    create_org_user(client, admin_token, org_id, "plain_member2@example.com", role="member")
    member_token = login(client, "plain_member2@example.com", "Password123!")
    resp = client.get(f"/api/v1/orgs/{org_id}/users?has_2fa=false", headers=auth_headers(member_token))
    assert resp.status_code == 403


def test_org_admin_of_a_different_org_cannot_use_filters_here(client, admin_token, org_id):
    """Cross-org boundary: an admin of org A must not be able to run
    access-review filters against org B just by knowing its id."""
    _, other_admin_token = create_org_admin_in(client, admin_token, "Other Org For Access Review")
    resp = client.get(f"/api/v1/orgs/{org_id}/users?is_active=true", headers=auth_headers(other_admin_token))
    assert resp.status_code == 403


def test_org_admin_can_filter_by_stale_login_and_never_logged_in(client, admin_token, org_id):
    create_org_user(client, admin_token, org_id, "never_logged_in@example.com", role="member")
    resp = client.get(f"/api/v1/orgs/{org_id}/users?never_logged_in=true", headers=auth_headers(admin_token))
    assert resp.status_code == 200
    emails = {u["email"] for u in resp.json()}
    assert "never_logged_in@example.com" in emails
    # The bootstrap admin has logged in (via the admin_token fixture itself).
    assert "admin@example.com" not in emails


def test_org_admin_can_filter_by_has_project_access(client, admin_token, org_id):
    from tests.conftest import create_project

    with_access_id = create_org_user(client, admin_token, org_id, "with_access@example.com", role="member")
    create_org_user(client, admin_token, org_id, "without_access@example.com", role="member")
    project = create_project(client, admin_token, org_id)
    client.post(
        f"/api/v1/projects/{project['id']}/roles", json={"user_id": with_access_id, "role": "member"},
        headers=auth_headers(admin_token),
    )

    resp = client.get(f"/api/v1/orgs/{org_id}/users?has_project_access=true", headers=auth_headers(admin_token))
    emails = {u["email"] for u in resp.json()}
    assert "with_access@example.com" in emails
    assert "without_access@example.com" not in emails


def test_system_users_endpoint_is_server_admin_only(client, admin_token, org_id):
    """A genuine org admin (not a server admin) must be rejected."""
    _, other_admin_token = create_org_admin_in(client, admin_token, "Org For System Users Check")
    resp = client.get("/api/v1/system/users", headers=auth_headers(other_admin_token))
    assert resp.status_code == 403


def test_system_users_orphaned_filter_finds_users_with_no_org_membership(client, admin_token, org_id):
    """C-A-13's literal clarification: enabled users in no organisation at
    all. The bootstrap admin belongs to an org, so must not appear."""
    resp = client.get("/api/v1/system/users?no_org_membership=true", headers=auth_headers(admin_token))
    assert resp.status_code == 200
    emails = {u["email"] for u in resp.json()}
    assert "admin@example.com" not in emails


def test_system_users_response_omits_org_scoped_fields(client, admin_token, org_id):
    """I-M-05: server admin must not see cross-tenant org-role/project-access
    data through this endpoint."""
    resp = client.get("/api/v1/system/users", headers=auth_headers(admin_token))
    assert resp.status_code == 200
    for user in resp.json():
        assert "roles" not in user
        assert "org_role" not in user


def _make_orphaned_user(client, admin_token, org_id, email):
    """Creates a real org member, then has them leave (self-service) so
    they end up with genuinely zero organisation membership — the only way
    to produce this state through the API, since native accounts can only
    ever be created scoped to an organisation."""
    user_id = create_org_user(client, admin_token, org_id, email, role="member")
    token = login(client, email, "Password123!")
    resp = client.delete(f"/api/v1/orgs/{org_id}/membership", headers=auth_headers(token))
    assert resp.status_code == 204
    return user_id


def test_orphaned_filter_excludes_server_admins_but_is_server_admin_filter_finds_them(client, admin_token, org_id):
    """Hardening-review regression: a server admin has no organisation
    membership *by design* (I-M-05) — that's the intended shape of the
    role, not an anomaly — so `no_org_membership=true` must not flag one as
    "orphaned" alongside genuinely-forgotten accounts. The independent
    `is_server_admin` filter is the correct way to review the server-admin
    roster, and does include org-affiliated admins too (I-M-08)."""
    orphaned_admin_id = _make_orphaned_user(client, admin_token, org_id, "orphaned_admin@example.com")
    client.put(
        f"/api/v1/system/users/{orphaned_admin_id}/server-admin", json={"is_server_admin": True},
        headers=auth_headers(admin_token),
    )

    resp = client.get("/api/v1/system/users?no_org_membership=true", headers=auth_headers(admin_token))
    assert resp.status_code == 200
    assert "orphaned_admin@example.com" not in {u["email"] for u in resp.json()}

    resp = client.get("/api/v1/system/users?is_server_admin=true", headers=auth_headers(admin_token))
    assert resp.status_code == 200
    assert "orphaned_admin@example.com" in {u["email"] for u in resp.json()}


def test_system_users_has_org_membership_field_reflects_reality(client, admin_token, org_id):
    orphaned_id = _make_orphaned_user(client, admin_token, org_id, "orphaned_plain@example.com")
    resp = client.get("/api/v1/system/users", headers=auth_headers(admin_token))
    by_email = {u["email"]: u for u in resp.json()}
    assert by_email["orphaned_plain@example.com"]["has_org_membership"] is False
    assert by_email["orphaned_plain@example.com"]["user_id"] == orphaned_id
    assert by_email["admin@example.com"]["has_org_membership"] is True


def test_deactivate_and_reactivate_orphaned_user(client, admin_token, org_id):
    """Hardening-review finding: an orphaned account could not be acted on
    by anyone at all — org-scoped `deactivate_org_user` requires the target
    to already belong to that org, which an orphaned user by definition
    doesn't. These new system-level endpoints close that gap."""
    orphaned_id = _make_orphaned_user(client, admin_token, org_id, "orphaned_to_deactivate@example.com")

    resp = client.post(f"/api/v1/system/users/{orphaned_id}/deactivate", headers=auth_headers(admin_token))
    assert resp.status_code == 204
    assert client.post(
        "/api/v1/auth/login", json={"email": "orphaned_to_deactivate@example.com", "password": "Password123!"}
    ).status_code == 401

    resp = client.post(f"/api/v1/system/users/{orphaned_id}/reactivate", headers=auth_headers(admin_token))
    assert resp.status_code == 204
    assert client.post(
        "/api/v1/auth/login", json={"email": "orphaned_to_deactivate@example.com", "password": "Password123!"}
    ).status_code == 200


def test_cannot_deactivate_or_reactivate_an_org_member_via_the_system_endpoint(client, admin_token, org_id):
    """A user who still belongs to an organisation must be managed through
    that organisation's own admin console, not the system-wide endpoint —
    a server admin's authority is tenancy-wide but content-free (I-M-05)."""
    member_id = create_org_user(client, admin_token, org_id, "still_a_member@example.com", role="member")
    resp = client.post(f"/api/v1/system/users/{member_id}/deactivate", headers=auth_headers(admin_token))
    assert resp.status_code == 400
    resp = client.post(f"/api/v1/system/users/{member_id}/reactivate", headers=auth_headers(admin_token))
    assert resp.status_code == 400


def test_cannot_deactivate_own_account_via_system_endpoint(client, admin_token):
    self_id = client.get("/api/v1/auth/me", headers=auth_headers(admin_token)).json()["id"]
    resp = client.post(f"/api/v1/system/users/{self_id}/deactivate", headers=auth_headers(admin_token))
    assert resp.status_code == 400


def test_cannot_revoke_the_deployment_last_active_server_admin(client, admin_token, org_id):
    """Hardening-review finding: revoking the sole remaining active server
    admin would be an unrecoverable lockout — nobody left with the
    authority to grant the role back to anyone, short of direct database
    access."""
    self_id = client.get("/api/v1/auth/me", headers=auth_headers(admin_token)).json()["id"]
    resp = client.put(
        f"/api/v1/system/users/{self_id}/server-admin", json={"is_server_admin": False},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 400

    # With a second active server admin, revoking either one is fine.
    second_admin_id = create_org_user(client, admin_token, org_id, "second_admin@example.com", role="member")
    client.put(
        f"/api/v1/system/users/{second_admin_id}/server-admin", json={"is_server_admin": True},
        headers=auth_headers(admin_token),
    )
    resp = client.put(
        f"/api/v1/system/users/{second_admin_id}/server-admin", json={"is_server_admin": False},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 204
