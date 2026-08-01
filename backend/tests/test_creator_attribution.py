"""Tests for project-manager creator reassignment at creation time
(C-A-11 requirements, C-A-12 change requests): a PM can attribute a new
requirement or change request to a different user than the one submitting
the API call, but non-managers cannot."""

from tests.conftest import auth_headers, create_component_and_category, create_org_user, create_project


def _make_member(client, admin_token, org_id, project_id, email):
    return create_org_user(client, admin_token, org_id, email, role="member")


def test_pm_can_reassign_requirement_creator(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    other_user_id = _make_member(client, admin_token, org_id, project["id"], "req_creator@example.com")

    resp = client.post(
        f"/api/v1/projects/{project['id']}/requirements",
        json={
            "name": "Boot fast", "component_id": component_id, "category_id": category_id,
            "creator_id": other_user_id,
        },
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["creator_id"] == other_user_id


def test_non_manager_cannot_reassign_requirement_creator(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    stakeholder_user_id = _make_member(client, admin_token, org_id, project["id"], "req_stakeholder@example.com")
    client.post(
        f"/api/v1/projects/{project['id']}/roles", json={"user_id": stakeholder_user_id, "role": "stakeholder"},
        headers=auth_headers(admin_token),
    )
    from tests.conftest import login

    stakeholder_token = login(client, "req_stakeholder@example.com", "Password123!")

    resp = client.post(
        f"/api/v1/projects/{project['id']}/requirements",
        json={
            "name": "Boot fast", "component_id": component_id, "category_id": category_id,
            "creator_id": stakeholder_user_id,
        },
        headers=auth_headers(stakeholder_token),
    )
    assert resp.status_code == 403


def test_pm_can_reassign_change_request_creator(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    other_user_id = _make_member(client, admin_token, org_id, project["id"], "cr_creator@example.com")

    resp = client.post(
        f"/api/v1/projects/{project['id']}/change-requests",
        json={
            "kind": "new_requirement", "proposed_name": "x", "reason": "y",
            "creator_id": other_user_id,
        },
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["creator_id"] == other_user_id


def test_non_manager_cannot_reassign_change_request_creator(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    member_user_id = _make_member(client, admin_token, org_id, project["id"], "cr_member@example.com")
    client.post(
        f"/api/v1/projects/{project['id']}/roles", json={"user_id": member_user_id, "role": "member"},
        headers=auth_headers(admin_token),
    )
    client.patch(
        f"/api/v1/projects/{project['id']}", json={"allow_member_change_requests": True},
        headers=auth_headers(admin_token),
    )
    from tests.conftest import login

    member_token = login(client, "cr_member@example.com", "Password123!")

    resp = client.post(
        f"/api/v1/projects/{project['id']}/change-requests",
        json={
            "kind": "new_requirement", "proposed_name": "x", "reason": "y",
            "creator_id": member_user_id,
        },
        headers=auth_headers(member_token),
    )
    assert resp.status_code == 403
