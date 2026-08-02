"""Tests for role-based access control boundaries (C-U-01, C-U-03)."""

from tests.conftest import auth_headers, create_component_and_category, create_org_user, create_project, login


def test_member_cannot_create_project(client, admin_token, org_id):
    create_org_user(client, admin_token, org_id, "member@example.com", role="member")
    token = login(client, "member@example.com", "Password123!")

    resp = client.post(
        "/api/v1/projects", json={"organization_id": org_id, "name": "Should Fail", "summary": ""},
        headers=auth_headers(token),
    )
    assert resp.status_code == 403


def test_project_creator_can_create_project(client, admin_token, org_id):
    create_org_user(client, admin_token, org_id, "creator@example.com", role="project_creator")
    token = login(client, "creator@example.com", "Password123!")

    resp = client.post(
        "/api/v1/projects", json={"organization_id": org_id, "name": "Allowed", "summary": ""},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201


def test_project_creator_becomes_project_manager(client, admin_token, org_id):
    """The project creator is added to the Project Managers group (C-U-10)."""
    create_org_user(client, admin_token, org_id, "creator2@example.com", role="project_creator")
    token = login(client, "creator2@example.com", "Password123!")
    project = client.post(
        "/api/v1/projects", json={"organization_id": org_id, "name": "PM Test", "summary": ""},
        headers=auth_headers(token),
    ).json()

    groups = client.get(f"/api/v1/projects/{project['id']}/groups", headers=auth_headers(token)).json()
    manager_group = next(g for g in groups if g["role"] == "project_manager")
    me = client.get("/api/v1/auth/me", headers=auth_headers(token)).json()
    assert me["id"] in manager_group["member_user_ids"]


def test_member_cannot_create_requirement(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    create_org_user(client, admin_token, org_id, "member2@example.com", role="member")

    # Project-level member role: give them member role on the project too.
    client.post(
        f"/api/v1/projects/{project['id']}/roles",
        json={"user_id": _user_id(client, admin_token, org_id, "member2@example.com"), "role": "member"},
        headers=auth_headers(admin_token),
    )
    token = login(client, "member2@example.com", "Password123!")
    resp = client.post(
        f"/api/v1/projects/{project['id']}/requirements",
        json={"name": "Should fail", "component_id": component_id, "category_id": category_id},
        headers=auth_headers(token),
    )
    assert resp.status_code == 403


def test_non_member_cannot_view_project(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    create_org_user(client, admin_token, org_id, "outsider@example.com", role="member")
    token = login(client, "outsider@example.com", "Password123!")

    resp = client.get(f"/api/v1/projects/{project['id']}", headers=auth_headers(token))
    assert resp.status_code == 403


def test_only_project_manager_can_approve_stage(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    create_org_user(client, admin_token, org_id, "admin_role@example.com", role="member")
    user_id = _user_id(client, admin_token, org_id, "admin_role@example.com")
    client.post(
        f"/api/v1/projects/{project['id']}/roles",
        json={"user_id": user_id, "role": "project_administrator"},
        headers=auth_headers(admin_token),
    )
    token = login(client, "admin_role@example.com", "Password123!")

    stages = client.get(f"/api/v1/projects/{project['id']}/stages", headers=auth_headers(token)).json()
    stage_id = stages[0]["id"]
    resp = client.post(
        f"/api/v1/projects/{project['id']}/stages/{stage_id}/transition?new_status=approved",
        headers=auth_headers(token),
    )
    assert resp.status_code == 403


def _user_id(client, admin_token, org_id, email) -> str:
    users = client.get(f"/api/v1/orgs/{org_id}/users", headers=auth_headers(admin_token)).json()
    return next(u["user_id"] for u in users if u["email"] == email)


def test_org_group_nested_in_project_group_grants_effective_role(client, admin_token, org_id):
    """C-U-12: a member of an organisation group nested into a project group
    must actually receive that project group's effective role. Regression
    test for a real bug caught by ruff (F821): `get_effective_project_roles`
    used `OrgGroup` in a live query but never imported it, so this exact
    path raised NameError at runtime whenever it executed."""
    project = create_project(client, admin_token, org_id)
    user_id = create_org_user(client, admin_token, org_id, "nested_member@example.com", role="member")

    org_group = client.post(
        f"/api/v1/orgs/{org_id}/groups", json={"name": "Dev Team"}, headers=auth_headers(admin_token)
    ).json()
    client.post(
        f"/api/v1/orgs/{org_id}/groups/{org_group['id']}/members",
        json={"user_id": user_id}, headers=auth_headers(admin_token),
    )

    project_group = client.post(
        f"/api/v1/projects/{project['id']}/groups", json={"name": "Stakeholders Team", "role": "stakeholder"},
        headers=auth_headers(admin_token),
    ).json()
    nested = client.post(
        f"/api/v1/projects/{project['id']}/groups/{project_group['id']}/members",
        json={"org_group_id": org_group["id"]}, headers=auth_headers(admin_token),
    )
    assert nested.status_code == 204, nested.text

    token = login(client, "nested_member@example.com", "Password123!")
    resp = client.get(f"/api/v1/projects/{project['id']}", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
