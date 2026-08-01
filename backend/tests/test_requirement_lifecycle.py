"""
Tests for the requirement lifecycle: creation, unique ID generation
(C-G-06, C-G-07), stage-approval baselining (C-G-10), the change-request-only
edit lock (C-G-12), and version history (C-A-02, C-A-09).
"""

from tests.conftest import auth_headers, create_component_and_category, create_project


def test_requirement_id_uses_component_and_category_prefix(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])

    resp = client.post(
        f"/api/v1/projects/{project['id']}/requirements",
        json={"name": "Boot fast", "component_id": component_id, "category_id": category_id, "keywords": ["perf"]},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["unique_code"] == "SW-PERF-001"
    assert body["status"] == "draft"
    assert body["is_locked"] is False
    assert body["keywords"] == ["perf"]


def test_second_requirement_gets_sequential_id(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    for _ in range(2):
        resp = client.post(
            f"/api/v1/projects/{project['id']}/requirements",
            json={"name": "Req", "component_id": component_id, "category_id": category_id},
            headers=auth_headers(admin_token),
        )
    assert resp.json()["unique_code"] == "SW-PERF-002"


def _create_requirement(client, admin_token, project_id, component_id, category_id, name="Boot fast"):
    resp = client.post(
        f"/api/v1/projects/{project_id}/requirements",
        json={"name": name, "component_id": component_id, "category_id": category_id},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 201
    return resp.json()


def _approve_current_stage(client, admin_token, project_id):
    stages = client.get(f"/api/v1/projects/{project_id}/stages", headers=auth_headers(admin_token)).json()
    stage_id = stages[0]["id"]
    resp = client.post(
        f"/api/v1/projects/{project_id}/stages/{stage_id}/transition?new_status=approved",
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 200
    return resp.json()


def test_stage_approval_locks_requirement_and_creates_baseline(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    requirement = _create_requirement(client, admin_token, project["id"], component_id, category_id)

    _approve_current_stage(client, admin_token, project["id"])

    resp = client.get(
        f"/api/v1/projects/{project['id']}/requirements/{requirement['id']}", headers=auth_headers(admin_token)
    )
    body = resp.json()
    assert body["status"] == "approved"
    assert body["is_locked"] is True


def test_direct_edit_rejected_once_locked(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    requirement = _create_requirement(client, admin_token, project["id"], component_id, category_id)
    _approve_current_stage(client, admin_token, project["id"])

    resp = client.put(
        f"/api/v1/projects/{project['id']}/requirements/{requirement['id']}",
        json={
            "name": "Direct edit attempt", "component_id": component_id, "category_id": category_id,
            "owner_id": requirement["owner_id"],
        },
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 409


def test_direct_edit_allowed_before_lock(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    requirement = _create_requirement(client, admin_token, project["id"], component_id, category_id)

    resp = client.put(
        f"/api/v1/projects/{project['id']}/requirements/{requirement['id']}",
        json={
            "name": "Edited during scoping", "component_id": component_id, "category_id": category_id,
            "owner_id": requirement["owner_id"], "change_note": "typo fix",
        },
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "Edited during scoping"


def test_change_request_modifies_locked_requirement_and_is_logged(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    requirement = _create_requirement(client, admin_token, project["id"], component_id, category_id)
    _approve_current_stage(client, admin_token, project["id"])

    cr = client.post(
        f"/api/v1/projects/{project['id']}/change-requests",
        json={
            "kind": "modify_requirement", "requirement_id": requirement["id"],
            "proposed_name": "Boot even faster", "proposed_reasoning": "New target", "reason": "Customer feedback",
        },
        headers=auth_headers(admin_token),
    ).json()

    client.post(f"/api/v1/projects/{project['id']}/change-requests/{cr['id']}/submit", headers=auth_headers(admin_token))
    decision = client.post(
        f"/api/v1/projects/{project['id']}/change-requests/{cr['id']}/decide",
        json={"approve": True, "note": "approved"}, headers=auth_headers(admin_token),
    )
    assert decision.status_code == 200
    assert decision.json()["status"] == "approved"

    updated = client.get(
        f"/api/v1/projects/{project['id']}/requirements/{requirement['id']}", headers=auth_headers(admin_token)
    ).json()
    assert updated["name"] == "Boot even faster"

    history = client.get(
        f"/api/v1/projects/{project['id']}/requirements/{requirement['id']}/history", headers=auth_headers(admin_token)
    ).json()
    assert len(history) == 3  # initial creation, stage-approval bump, change-request update
    assert history[-1]["change_request_id"] == cr["id"]


def test_archiving_preserves_history(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    requirement = _create_requirement(client, admin_token, project["id"], component_id, category_id)

    resp = client.delete(
        f"/api/v1/projects/{project['id']}/requirements/{requirement['id']}", headers=auth_headers(admin_token)
    )
    assert resp.status_code == 204

    listed = client.get(f"/api/v1/projects/{project['id']}/requirements", headers=auth_headers(admin_token)).json()
    assert requirement["id"] not in [r["id"] for r in listed]

    history = client.get(
        f"/api/v1/projects/{project['id']}/requirements/{requirement['id']}/history", headers=auth_headers(admin_token)
    ).json()
    assert len(history) == 1
