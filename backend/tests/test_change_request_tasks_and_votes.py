"""Tests for Massif (v3) change-request tasks (C-R-02/04) and stakeholder
advisory voting (C-R-03)."""

from tests.conftest import auth_headers, create_component_and_category, create_org_user, create_project, login


def _submitted_cr(client, admin_token, project_id, component_id, category_id):
    req = client.post(
        f"/api/v1/projects/{project_id}/requirements",
        json={"name": "Base req", "component_id": component_id, "category_id": category_id},
        headers=auth_headers(admin_token),
    ).json()
    cr = client.post(
        f"/api/v1/projects/{project_id}/change-requests",
        json={
            "kind": "modify_requirement", "requirement_id": req["id"], "changed_fields": ["name"],
            "proposed_name": "Base req v2", "reason": "testing",
        },
        headers=auth_headers(admin_token),
    ).json()
    client.post(f"/api/v1/projects/{project_id}/change-requests/{cr['id']}/submit", headers=auth_headers(admin_token))
    return cr


def test_project_manager_can_create_and_complete_a_task(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    cr = _submitted_cr(client, admin_token, project["id"], component_id, category_id)

    resp = client.post(
        f"/api/v1/projects/{project['id']}/change-requests/{cr['id']}/tasks",
        json={"description": "Check with legal"}, headers=auth_headers(admin_token),
    )
    assert resp.status_code == 201, resp.text
    task = resp.json()
    assert task["is_done"] is False

    resp = client.patch(
        f"/api/v1/projects/{project['id']}/change-requests/{cr['id']}/tasks/{task['id']}",
        json={"is_done": True}, headers=auth_headers(admin_token),
    )
    assert resp.status_code == 200
    assert resp.json()["is_done"] is True
    assert resp.json()["completed_at"] is not None


def test_non_manager_cannot_create_a_task(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    cr = _submitted_cr(client, admin_token, project["id"], component_id, category_id)

    member_id = create_org_user(client, admin_token, org_id, "member1@example.com", role="member")
    client.post(
        f"/api/v1/projects/{project['id']}/roles", json={"user_id": member_id, "role": "stakeholder"},
        headers=auth_headers(admin_token),
    )
    member_token = login(client, "member1@example.com", "Password123!")

    resp = client.post(
        f"/api/v1/projects/{project['id']}/change-requests/{cr['id']}/tasks",
        json={"description": "Sneaky task"}, headers=auth_headers(member_token),
    )
    assert resp.status_code == 403


def test_assignee_can_mark_their_own_task_done_without_manager_rights(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    cr = _submitted_cr(client, admin_token, project["id"], component_id, category_id)

    member_id = create_org_user(client, admin_token, org_id, "assignee@example.com", role="member")
    client.post(
        f"/api/v1/projects/{project['id']}/roles", json={"user_id": member_id, "role": "stakeholder"},
        headers=auth_headers(admin_token),
    )
    member_token = login(client, "assignee@example.com", "Password123!")

    task = client.post(
        f"/api/v1/projects/{project['id']}/change-requests/{cr['id']}/tasks",
        json={"description": "Investigate", "assignee_id": member_id}, headers=auth_headers(admin_token),
    ).json()

    resp = client.patch(
        f"/api/v1/projects/{project['id']}/change-requests/{cr['id']}/tasks/{task['id']}",
        json={"is_done": True}, headers=auth_headers(member_token),
    )
    assert resp.status_code == 200
    assert resp.json()["is_done"] is True

    # Same assignee cannot reassign the task without manager rights.
    resp = client.patch(
        f"/api/v1/projects/{project['id']}/change-requests/{cr['id']}/tasks/{task['id']}",
        json={"description": "Rewritten"}, headers=auth_headers(member_token),
    )
    assert resp.status_code == 403


def test_stakeholder_can_vote_and_tally_reflects_it(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    cr = _submitted_cr(client, admin_token, project["id"], component_id, category_id)

    member_id = create_org_user(client, admin_token, org_id, "voter@example.com", role="member")
    client.post(
        f"/api/v1/projects/{project['id']}/roles", json={"user_id": member_id, "role": "stakeholder"},
        headers=auth_headers(admin_token),
    )
    voter_token = login(client, "voter@example.com", "Password123!")

    resp = client.post(
        f"/api/v1/projects/{project['id']}/change-requests/{cr['id']}/votes",
        json={"vote": "approve"}, headers=auth_headers(voter_token),
    )
    assert resp.status_code == 200

    resp = client.get(f"/api/v1/projects/{project['id']}/change-requests/{cr['id']}/votes", headers=auth_headers(admin_token))
    assert resp.status_code == 200
    body = resp.json()
    assert body["approve_count"] == 1
    assert body["reject_count"] == 0


def test_voting_again_updates_existing_vote_not_duplicates(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    cr = _submitted_cr(client, admin_token, project["id"], component_id, category_id)

    client.post(
        f"/api/v1/projects/{project['id']}/change-requests/{cr['id']}/votes",
        json={"vote": "approve"}, headers=auth_headers(admin_token),
    )
    client.post(
        f"/api/v1/projects/{project['id']}/change-requests/{cr['id']}/votes",
        json={"vote": "reject"}, headers=auth_headers(admin_token),
    )
    resp = client.get(f"/api/v1/projects/{project['id']}/change-requests/{cr['id']}/votes", headers=auth_headers(admin_token))
    body = resp.json()
    assert len(body["votes"]) == 1
    assert body["approve_count"] == 0
    assert body["reject_count"] == 1


def test_voting_is_advisory_and_does_not_auto_decide(client, admin_token, org_id):
    """A vote must never change the change request's own status."""
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    cr = _submitted_cr(client, admin_token, project["id"], component_id, category_id)

    client.post(
        f"/api/v1/projects/{project['id']}/change-requests/{cr['id']}/votes",
        json={"vote": "reject"}, headers=auth_headers(admin_token),
    )
    resp = client.get(f"/api/v1/projects/{project['id']}/change-requests/{cr['id']}", headers=auth_headers(admin_token))
    assert resp.json()["status"] == "submitted"
