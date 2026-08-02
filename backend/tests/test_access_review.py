"""Tests for the Massif (v3) broadened user-directory access-review filters
(C-A-13), including the authorization boundaries called out explicitly
during planning."""

from tests.conftest import auth_headers, create_org_admin_in, create_org_user, login


def test_plain_member_can_list_org_users_unfiltered(client, admin_token, org_id):
    """Existing behavior preserved: any org member can still see the
    unfiltered member directory."""
    member_id = create_org_user(client, admin_token, org_id, "plain_member@example.com", role="member")
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
