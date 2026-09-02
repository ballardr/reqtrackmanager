"""Tests for `GET /orgs/{org_id}/users/{user_id}/access` (2026-08 UX audit,
sixth pass: "No way to view a user's access") — an org admin's read-only
summary of what one user can actually reach: their direct org groups, and
every project where they hold at least one effective role, with that
role set and which of the project's own groups they directly belong to."""

from tests.conftest import auth_headers, create_org_user, create_project, login


def test_user_access_lists_org_groups_and_project_roles(client, admin_token, org_id):
    user_id = create_org_user(client, admin_token, org_id, "access_summary_user@example.com")

    org_group = client.post(
        f"/api/v1/orgs/{org_id}/groups", json={"name": "Access Summary Org Group"}, headers=auth_headers(admin_token)
    ).json()
    client.post(
        f"/api/v1/orgs/{org_id}/groups/{org_group['id']}/members",
        json={"user_id": user_id}, headers=auth_headers(admin_token),
    )

    direct_project = create_project(client, admin_token, org_id, "Access Summary Direct Project")
    client.post(
        f"/api/v1/projects/{direct_project['id']}/roles",
        json={"user_id": user_id, "role": "stakeholder"}, headers=auth_headers(admin_token),
    )

    group_project = create_project(client, admin_token, org_id, "Access Summary Group Project")
    project_group = client.post(
        f"/api/v1/projects/{group_project['id']}/groups",
        json={"name": "Access Summary Project Group"}, headers=auth_headers(admin_token),
    ).json()
    grant = client.post(
        f"/api/v1/projects/{group_project['id']}/groups/{project_group['id']}/roles",
        json={"role": "member"}, headers=auth_headers(admin_token),
    )
    assert grant.status_code == 204, grant.text
    client.post(
        f"/api/v1/projects/{group_project['id']}/groups/{project_group['id']}/members",
        json={"user_id": user_id}, headers=auth_headers(admin_token),
    )

    # No access at all — must not appear in the result.
    create_project(client, admin_token, org_id, "Access Summary No Access Project")

    resp = client.get(f"/api/v1/orgs/{org_id}/users/{user_id}/access", headers=auth_headers(admin_token))
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert [g["name"] for g in body["org_groups"]] == ["Access Summary Org Group"]

    by_name = {p["project_name"]: p for p in body["projects"]}
    assert "Access Summary No Access Project" not in by_name

    direct = by_name["Access Summary Direct Project"]
    assert "stakeholder" in direct["roles"]
    assert direct["project_groups"] == []

    via_group = by_name["Access Summary Group Project"]
    assert "member" in via_group["roles"]
    assert [g["name"] for g in via_group["project_groups"]] == ["Access Summary Project Group"]


def test_user_access_requires_org_admin(client, admin_token, org_id):
    user_id = create_org_user(client, admin_token, org_id, "access_summary_nonadmin@example.com", role="member")
    member_token = login(client, "access_summary_nonadmin@example.com", "Password123!")

    resp = client.get(f"/api/v1/orgs/{org_id}/users/{user_id}/access", headers=auth_headers(member_token))
    assert resp.status_code == 403


def test_user_access_404s_for_unknown_user(client, admin_token, org_id):
    resp = client.get(
        f"/api/v1/orgs/{org_id}/users/00000000-0000-0000-0000-000000000000/access",
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 404
