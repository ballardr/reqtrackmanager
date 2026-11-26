"""Tests that a project stage and a component's track are lifecycles of the engine (`services.lifecycles_core`): their states
are the kinds of phase a workflow defines, a project may turn off Review (a move to a review phase is then refused and a
move past it is accepted), an organisation may require it, a stage with review on moves as before, and the same check
guards the daily sweep and a component's track. The workflow, baseline and lock rules are pinned by `test_stage_workflows.py`
and `test_component_stages.py`."""

from __future__ import annotations

from app.modules.registry import get_lifecycles
from app.services.lifecycles import validate_definition
from app.services.lifecycles_core import COMPONENT_STAGE_TYPE, PROJECT_STAGE_TYPE, STAGE_PHASE_KIND_LABEL
from tests.conftest import auth_headers, create_org_admin_in, create_project
from tests.stage_helpers import move_stage
from tests.test_component_stages import _components, _move, _stages, _turn_on, _workflow


def _setup(client, admin_token, name):
    org, token = create_org_admin_in(client, admin_token, name)
    return org, create_project(client, token, org["id"], f"{name} project"), token


def _turn_off_review(client, token, project_id, artefact_type) -> None:
    resp = client.put(
        f"/api/v1/projects/{project_id}/lifecycles/{artefact_type}", json={"disabled_states": ["review"]}, headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text


def test_a_stage_and_a_track_are_registered_by_phase_kind():
    registered = get_lifecycles()
    for artefact_type in (PROJECT_STAGE_TYPE, COMPONENT_STAGE_TYPE):
        module_key, definition = registered[artefact_type]
        assert module_key == "" and validate_definition(definition) == []
        assert definition.path == ("open", "review", "locked", "closed")
        assert definition.optional == ("review",) and definition.gated == ()
        assert set(definition.transitions) == set(STAGE_PHASE_KIND_LABEL)
        assert all(definition.transitions[kind] == set(STAGE_PHASE_KIND_LABEL) - {kind} for kind in definition.transitions)


def test_with_review_on_a_stage_moves_between_every_kind_as_before(client, admin_token):
    _org, project, token = _setup(client, admin_token, "Stage Lifecycle On Co")
    headers = auth_headers(token)
    stage_id = _stages(client, token, project["id"])[0]["id"]
    for phase in ("review", "scoping", "approved", "review", "completed", "archived"):
        assert move_stage(client, project["id"], stage_id, phase, headers=headers).status_code == 200


def test_a_project_that_turned_review_off_refuses_a_review_phase_and_allows_the_rest(client, admin_token):
    _org, project, token = _setup(client, admin_token, "Stage Lifecycle Off Co")
    headers = auth_headers(token)
    stage_id = _stages(client, token, project["id"])[0]["id"]
    _turn_off_review(client, token, project["id"], PROJECT_STAGE_TYPE)

    refused = move_stage(client, project["id"], stage_id, "review", headers=headers)
    assert refused.status_code == 409 and "turned off" in refused.json()["detail"]
    assert move_stage(client, project["id"], stage_id, "approved", headers=headers).status_code == 200
    assert move_stage(client, project["id"], stage_id, "scoping", headers=headers).status_code == 200


def test_an_organisation_requirement_stops_a_project_turning_review_off(client, admin_token):
    org, project, token = _setup(client, admin_token, "Stage Lifecycle Required Co")
    required = client.put(
        f"/api/v1/orgs/{org['id']}/lifecycles/{PROJECT_STAGE_TYPE}", json={"required_states": ["review"]}, headers=auth_headers(token),
    )
    assert required.status_code == 200, required.text
    refused = client.put(
        f"/api/v1/projects/{project['id']}/lifecycles/{PROJECT_STAGE_TYPE}", json={"disabled_states": ["review"]}, headers=auth_headers(token),
    )
    assert refused.status_code == 409 and "requires" in refused.json()["detail"]
    stage_id = _stages(client, token, project["id"])[0]["id"]
    assert move_stage(client, project["id"], stage_id, "review", headers=auth_headers(token)).status_code == 200


def test_a_components_track_follows_its_own_lifecycle(client, admin_token):
    _org, project, token = _setup(client, admin_token, "Track Lifecycle Co")
    pid = project["id"]
    headers = auth_headers(token)
    component = client.post(f"/api/v1/projects/{pid}/components", json={"name": "Software", "prefix": "SW"}, headers=headers).json()
    stage_id = _stages(client, token, pid)[0]["id"]
    _turn_on(client, token, pid)
    workflow = _workflow(client, token, pid)
    assert _components(client, token, pid)

    _turn_off_review(client, token, pid, COMPONENT_STAGE_TYPE)
    refused = _move(client, token, pid, component["id"], stage_id, workflow, "Review")
    assert refused.status_code == 409 and "turned off" in refused.json()["detail"]
    assert move_stage(client, pid, stage_id, "review", headers=headers).status_code == 200  # the stage has its own setting
    assert _move(client, token, pid, component["id"], stage_id, workflow, "Approved").status_code == 200
