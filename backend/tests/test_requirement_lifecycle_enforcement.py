"""Tests that the Requirement endpoints enforce the project's lifecycle (`services.lifecycles.check_move` through
`services.requirements.check_status_move`): a state the project turned off cannot be entered by a direct edit but is stepped
over by an approval, a requirement parked in a state that is later turned off still moves on (an approval, a stage
baseline), and a move to the status a requirement already has is not a move. The Requirement's table lets a draft be approved
directly, so a state the organisation requires only stops a project turning it off (`test_core_lifecycles.py`), and a skip
of steps has nothing to pass over for the core types. The tests run with no governance module."""

from __future__ import annotations

from tests.conftest import auth_headers, create_component_and_category
from tests.stage_helpers import move_stage
from tests.test_core_lifecycles import _edit_status, _setup


def _requirement(client, token, project_id, scope: tuple[str, str], name: str = "Boot fast") -> str:
    resp = client.post(
        f"/api/v1/projects/{project_id}/requirements",
        json={"name": name, "component_id": scope[0], "category_id": scope[1]}, headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _turn_off_reviewed(client, token, project_id) -> None:
    resp = client.put(
        f"/api/v1/projects/{project_id}/lifecycles/requirement", json={"disabled_states": ["reviewed"]}, headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text


def _approve(client, token, project_id, requirement_id):
    return client.post(f"/api/v1/projects/{project_id}/requirements/{requirement_id}/approve", json={}, headers=auth_headers(token))


def _status(client, token, project_id, requirement_id) -> str:
    return client.get(f"/api/v1/projects/{project_id}/requirements/{requirement_id}", headers=auth_headers(token)).json()["status"]


def test_a_state_the_project_turned_off_cannot_be_entered_but_is_stepped_over(client, admin_token):
    _, project, token = _setup(client, admin_token, "Enforce Off Co")
    pid = project["id"]
    _turn_off_reviewed(client, token, pid)
    requirement = _requirement(client, token, pid, create_component_and_category(client, token, pid))

    refused = _edit_status(client, token, pid, requirement, "reviewed")
    assert refused.status_code == 409 and "turned off" in refused.json()["detail"]
    assert _status(client, token, pid, requirement) == "draft"
    assert _approve(client, token, pid, requirement).status_code == 200


def test_a_move_to_the_status_a_requirement_already_has_is_not_a_move(client, admin_token):
    _, project, token = _setup(client, admin_token, "Enforce Same Co")
    pid = project["id"]
    requirement = _requirement(client, token, pid, create_component_and_category(client, token, pid))
    assert _edit_status(client, token, pid, requirement, "reviewed").status_code == 200
    _turn_off_reviewed(client, token, pid)
    assert _edit_status(client, token, pid, requirement, "reviewed").status_code == 200  # a re-save in the parked state
    assert _edit_status(client, token, pid, requirement, "archived").status_code == 200
    refused = _edit_status(client, token, pid, requirement, "reviewed")
    assert refused.status_code == 409 and "turned off" in refused.json()["detail"]
    assert _edit_status(client, token, pid, requirement, "draft").status_code == 200


def test_a_requirement_parked_in_a_state_later_turned_off_is_approved_and_baselined(client, admin_token):
    _, project, token = _setup(client, admin_token, "Enforce Parked Co")
    pid = project["id"]
    headers = auth_headers(token)
    scope = create_component_and_category(client, token, pid)
    parked = _requirement(client, token, pid, scope, "Parked")
    draft = _requirement(client, token, pid, scope, "Draft")
    assert _edit_status(client, token, pid, parked, "reviewed").status_code == 200
    _turn_off_reviewed(client, token, pid)

    assert _approve(client, token, pid, parked).status_code == 200
    stage_id = client.get(f"/api/v1/projects/{pid}/stages", headers=headers).json()[0]["id"]
    assert move_stage(client, pid, stage_id, "approved", headers=headers).status_code == 200
    assert _status(client, token, pid, draft) == "approved"
