"""Stage usage: the navigation offers Delivery status only for a project that goes beyond its one default stage
(several stages, a stage moved on, an owner, a phase schedule, or component phases on), and only to those who can view
the project."""

from tests.conftest import auth_headers, create_org_user, create_project, login
from tests.stage_helpers import move_stage


def _usage(client, token, project_id):
    return client.get(f"/api/v1/projects/{project_id}/stage-usage", headers=auth_headers(token))


def _in_use(client, token, project_id) -> bool:
    response = _usage(client, token, project_id)
    assert response.status_code == 200
    return response.json()["in_use"]


def _stage(client, token, project_id) -> dict:
    return client.get(f"/api/v1/projects/{project_id}/stages", headers=auth_headers(token)).json()[0]


def test_a_new_project_with_its_default_stage_is_not_using_stages(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id, "Untouched stages")
    assert _in_use(client, admin_token, project["id"]) is False


def test_a_second_stage_makes_stages_in_use(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id, "Two stages")
    created = client.post(f"/api/v1/projects/{project['id']}/stages", json={"name": "Build"}, headers=auth_headers(admin_token))
    assert created.status_code == 201
    assert _in_use(client, admin_token, project["id"]) is True


def test_moving_the_stage_on_makes_stages_in_use(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id, "Moved stage")
    stage = _stage(client, admin_token, project["id"])
    assert move_stage(client, project["id"], stage["id"], "review", headers=auth_headers(admin_token)).status_code == 200
    assert _in_use(client, admin_token, project["id"]) is True


def test_a_phase_schedule_makes_stages_in_use(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id, "Scheduled stage")
    stage = _stage(client, admin_token, project["id"])
    put = client.put(
        f"/api/v1/projects/{project['id']}/stages/{stage['id']}/phase-plan",
        json={"phase_id": stage["phase_id"], "expected_from": "2026-12-01", "expected_to": "2026-12-31"},
        headers=auth_headers(admin_token),
    )
    assert put.status_code == 200
    assert _in_use(client, admin_token, project["id"]) is True


def test_a_stage_owner_makes_stages_in_use(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id, "Owned stage")
    stage = _stage(client, admin_token, project["id"])
    me = client.get("/api/v1/auth/me", headers=auth_headers(admin_token)).json()
    patched = client.patch(
        f"/api/v1/projects/{project['id']}/stages/{stage['id']}",
        json={"name": stage["name"], "owner": {"type": "user", "id": me["id"]}}, headers=auth_headers(admin_token),
    )
    assert patched.status_code == 200
    assert _in_use(client, admin_token, project["id"]) is True


def test_turning_component_phases_on_makes_stages_in_use(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id, "Component phases on")
    on = client.put(f"/api/v1/projects/{project['id']}/component-phases-settings", json={"mode": "on"}, headers=auth_headers(admin_token))
    assert on.status_code == 200
    assert _in_use(client, admin_token, project["id"]) is True


def test_only_someone_who_can_view_the_project_may_ask(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id, "Private usage")
    create_org_user(client, admin_token, org_id, "usage-outsider@example.com")
    token = login(client, "usage-outsider@example.com", "Password123!")
    assert _usage(client, token, project["id"]).status_code in (403, 404)
