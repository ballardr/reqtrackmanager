"""
Tests for the requirement lifecycle: creation, unique ID generation
(C-G-06, C-G-07), stage-approval baselining (C-G-10), the change-request-only
edit lock (C-G-12), and version history (C-A-02, C-A-09).
"""

from tests.conftest import auth_headers, create_component_and_category, create_org_user, create_project, login


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
    review = client.post(
        f"/api/v1/projects/{project_id}/stages/{stage_id}/transition?new_status=review",
        headers=auth_headers(admin_token),
    )
    assert review.status_code == 200
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
            "changed_fields": ["name", "reasoning"],
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


def test_unarchive_requirement_restores_it_and_is_idempotent(client, admin_token, org_id):
    """Pins the `/unarchive` counterpart to `test_archiving_preserves_history`
    above (2026-08 UX audit roadmap: archive was previously one-way for
    requirements, unlike projects). Also covers the idempotency contract:
    unlike `archive_action`'s 409-on-already-archived, calling unarchive on
    an already-active requirement is a no-op, matching
    `unarchive_project`'s own shape."""
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    requirement = _create_requirement(client, admin_token, project["id"], component_id, category_id)

    client.delete(
        f"/api/v1/projects/{project['id']}/requirements/{requirement['id']}", headers=auth_headers(admin_token)
    )
    listed = client.get(f"/api/v1/projects/{project['id']}/requirements", headers=auth_headers(admin_token)).json()
    assert requirement["id"] not in [r["id"] for r in listed]

    resp = client.post(
        f"/api/v1/projects/{project['id']}/requirements/{requirement['id']}/unarchive",
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 200
    assert resp.json()["is_archived"] is False

    listed = client.get(f"/api/v1/projects/{project['id']}/requirements", headers=auth_headers(admin_token)).json()
    assert requirement["id"] in [r["id"] for r in listed]

    # Idempotent: unarchiving an already-active requirement doesn't error.
    again = client.post(
        f"/api/v1/projects/{project['id']}/requirements/{requirement['id']}/unarchive",
        headers=auth_headers(admin_token),
    )
    assert again.status_code == 200
    assert again.json()["is_archived"] is False


def test_unarchive_requirement_requires_manager_or_admin_role(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    requirement = _create_requirement(client, admin_token, project["id"], component_id, category_id)
    client.delete(
        f"/api/v1/projects/{project['id']}/requirements/{requirement['id']}", headers=auth_headers(admin_token)
    )

    user_id = create_org_user(client, admin_token, org_id, "stakeholder_unarchive@example.com", role="member")
    client.post(
        f"/api/v1/projects/{project['id']}/roles", json={"user_id": user_id, "role": "stakeholder"},
        headers=auth_headers(admin_token),
    )
    stakeholder_token = login(client, "stakeholder_unarchive@example.com", "Password123!")

    resp = client.post(
        f"/api/v1/projects/{project['id']}/requirements/{requirement['id']}/unarchive",
        headers=auth_headers(stakeholder_token),
    )
    assert resp.status_code == 403


def test_import_creates_valid_rows_and_reports_errors_for_invalid_ones(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    stages = client.get(f"/api/v1/projects/{project['id']}/stages", headers=auth_headers(admin_token)).json()
    stage_name = stages[0]["name"]

    csv_content = (
        "name,reasoning,component_prefix,category_prefix,level,target_version\n"
        f"Ship the widget,Because it must,SW,PERF,recommended,{stage_name}\n"
        ",Missing name,SW,PERF,requirement,\n"
        "Bad component,Oops,ZZ,PERF,requirement,\n"
        "Bad category,Oops,SW,ZZ,requirement,\n"
        "Bad level,Oops,SW,PERF,not_a_level,\n"
        "Bad stage,Oops,SW,PERF,requirement,Nonexistent Stage\n"
        "Second valid row,Also fine,SW,PERF,requirement,\n"
    )
    resp = client.post(
        f"/api/v1/projects/{project['id']}/requirements/import",
        files={"file": ("import.csv", csv_content, "text/csv")},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["created"] == 2
    assert len(body["errors"]) == 5

    listed = client.get(f"/api/v1/projects/{project['id']}/requirements", headers=auth_headers(admin_token)).json()
    names = {r["name"] for r in listed}
    assert "Ship the widget" in names
    assert "Second valid row" in names
    imported = next(r for r in listed if r["name"] == "Ship the widget")
    assert imported["level"] == "recommended"
    assert imported["target_stage_id"] == stages[0]["id"]


def test_target_stage_and_level_persist_through_create_update_and_change_request(client, admin_token, org_id):
    """target_stage_id can never become unset (it's mandatory) — this
    covers create with an explicit target, retargeting to a *different*
    stage via direct edit (not clearing it), omitting it on an unrelated
    edit (carries the current value forward unchanged), and retargeting
    again via an approved change request."""
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    stages = client.get(f"/api/v1/projects/{project['id']}/stages", headers=auth_headers(admin_token)).json()
    stage_id = stages[0]["id"]
    second_stage = client.post(
        f"/api/v1/projects/{project['id']}/stages", json={"name": "Detailed Design"}, headers=auth_headers(admin_token),
    ).json()

    created = client.post(
        f"/api/v1/projects/{project['id']}/requirements",
        json={
            "name": "Ship the widget", "component_id": component_id, "category_id": category_id,
            "target_stage_id": stage_id, "level": "recommended",
        },
        headers=auth_headers(admin_token),
    ).json()
    assert created["target_stage_id"] == stage_id
    assert created["level"] == "recommended"

    # Retargeted to a different stage (not cleared).
    updated = client.put(
        f"/api/v1/projects/{project['id']}/requirements/{created['id']}",
        json={
            "name": created["name"], "component_id": component_id, "category_id": category_id,
            "owner_id": created["owner_id"], "target_stage_id": second_stage["id"], "level": "requirement",
        },
        headers=auth_headers(admin_token),
    ).json()
    assert updated["target_stage_id"] == second_stage["id"]
    assert updated["level"] == "requirement"

    # Omitted on an unrelated edit: carries the current (retargeted) value forward.
    unrelated_edit = client.put(
        f"/api/v1/projects/{project['id']}/requirements/{created['id']}",
        json={
            "name": "Ship the widget (renamed)", "component_id": component_id, "category_id": category_id,
            "owner_id": created["owner_id"], "level": "requirement",
        },
        headers=auth_headers(admin_token),
    ).json()
    assert unrelated_edit["target_stage_id"] == second_stage["id"]

    cr = client.post(
        f"/api/v1/projects/{project['id']}/change-requests",
        json={
            "kind": "modify_requirement", "requirement_id": created["id"],
            "changed_fields": ["reasoning", "target_stage_id", "level"],
            "proposed_reasoning": "Refined target",
            "proposed_target_stage_id": stage_id, "proposed_level": "recommended",
            "reason": "Rescheduled",
        },
        headers=auth_headers(admin_token),
    ).json()
    assert cr["proposed_target_stage_id"] == stage_id
    assert cr["proposed_level"] == "recommended"

    client.post(f"/api/v1/projects/{project['id']}/change-requests/{cr['id']}/submit", headers=auth_headers(admin_token))
    decision = client.post(
        f"/api/v1/projects/{project['id']}/change-requests/{cr['id']}/decide",
        json={"approve": True, "note": "approved"}, headers=auth_headers(admin_token),
    )
    assert decision.status_code == 200

    final = client.get(
        f"/api/v1/projects/{project['id']}/requirements/{created['id']}", headers=auth_headers(admin_token)
    ).json()
    assert final["target_stage_id"] == stage_id
    assert final["level"] == "recommended"
