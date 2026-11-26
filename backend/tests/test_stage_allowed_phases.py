"""The phases a stage or a component's track cannot move to: both responses list them with a reason from the project's
effective lifecycle (`stage_workflows.PhaseMoves`), the stage and the track are resolved separately, the answer matches
what the transition endpoints accept, and the number of statements behind the responses does not grow."""

from __future__ import annotations

from sqlalchemy import event

from app.database import engine
from tests.conftest import auth_headers, create_org_admin_in, create_project
from tests.stage_helpers import move_stage, stage_phase_id


def _setup(client, admin_token, name):
    org, token = create_org_admin_in(client, admin_token, name)
    return org, create_project(client, token, org["id"], f"{name} project"), token


def _url(project_id, tail="") -> str:
    return f"/api/v1/projects/{project_id}/{tail}"


def _stages(client, token, project_id) -> list[dict]:
    resp = client.get(_url(project_id, "stages"), headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return resp.json()


def _disable(client, token, project_id, artefact_type, states) -> None:
    resp = client.put(
        _url(project_id, f"lifecycles/{artefact_type}"), json={"disabled_states": states}, headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text


def _phase_names(client, token, project_id, stage, ids) -> set[str]:
    workflows = client.get(_url(project_id, "stage-workflows"), headers=auth_headers(token)).json()
    workflow = next(w for w in workflows if w["id"] == stage["workflow_id"])
    return {p["name"] for p in workflow["phases"] if p["id"] in ids}


def _component_with_tracks(client, token, project_id) -> dict:
    component = client.post(
        _url(project_id, "components"), json={"name": "Software", "prefix": "SW"}, headers=auth_headers(token),
    ).json()
    resp = client.put(_url(project_id, "component-phases-settings"), json={"mode": "on"}, headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return component


def _tracks(client, token, project_id) -> list[dict]:
    return client.get(_url(project_id, "component-stages"), headers=auth_headers(token)).json()["tracks"]


def test_a_project_that_turns_nothing_off_offers_every_phase(client, admin_token):
    _, project, token = _setup(client, admin_token, "Allowed Phases Default Co")
    assert [s["unavailable_phases"] for s in _stages(client, token, project["id"])] == [[]]


def test_a_stage_cannot_move_to_the_review_phase_when_review_is_off(client, admin_token):
    _, project, token = _setup(client, admin_token, "Allowed Phases Review Off Co")
    pid = project["id"]
    _disable(client, token, pid, "project_stage", ["review"])
    stage = _stages(client, token, pid)[0]
    unavailable = stage["unavailable_phases"]
    assert _phase_names(client, token, pid, stage, {u["phase_id"] for u in unavailable}) == {"Review"}
    assert unavailable[0]["reason"] == "Review phases are turned off in this project."


def test_a_stage_and_a_track_are_resolved_separately(client, admin_token):
    _, project, token = _setup(client, admin_token, "Allowed Phases Separate Co")
    pid = project["id"]
    _component_with_tracks(client, token, pid)
    _disable(client, token, pid, "component_stage", ["review"])
    stage = _stages(client, token, pid)[0]
    assert stage["unavailable_phases"] == []
    track = _tracks(client, token, pid)[0]
    assert _phase_names(client, token, pid, stage, {u["phase_id"] for u in track["unavailable_phases"]}) == {"Review"}

    _disable(client, token, pid, "component_stage", [])
    _disable(client, token, pid, "project_stage", ["review"])
    assert _stages(client, token, pid)[0]["unavailable_phases"] != []
    assert _tracks(client, token, pid)[0]["unavailable_phases"] == []


def test_the_response_and_the_transition_endpoint_agree_for_every_phase(client, admin_token):
    _, project, token = _setup(client, admin_token, "Allowed Phases Agree Co")
    pid = project["id"]
    _disable(client, token, pid, "project_stage", ["review"])
    headers = auth_headers(token)
    workflows = client.get(_url(pid, "stage-workflows"), headers=headers).json()
    workflow = next(w for w in workflows if w["name"] == "Standard")
    for phase in workflow["phases"]:
        stage = client.post(_url(pid, "stages"), json={"name": f"Try {phase['name']}"}, headers=headers).json()
        current = stage["phase_id"]
        if phase["id"] == current:
            continue
        listed = {u["phase_id"]: u["reason"] for u in stage["unavailable_phases"]}
        moved = move_stage(client, pid, stage["id"], phase["name"], headers=headers)
        if phase["id"] in listed:
            assert moved.status_code == 409, (phase["name"], moved.text)
            assert listed[phase["id"]] in moved.text or "turned off" in moved.text
        else:
            assert moved.status_code == 200, (phase["name"], moved.text)


def test_the_track_response_and_its_transition_agree(client, admin_token):
    _, project, token = _setup(client, admin_token, "Allowed Phases Track Agree Co")
    pid = project["id"]
    component = _component_with_tracks(client, token, pid)
    _disable(client, token, pid, "component_stage", ["review"])
    headers = auth_headers(token)
    stage = _stages(client, token, pid)[0]
    track = _tracks(client, token, pid)[0]
    blocked = {u["phase_id"] for u in track["unavailable_phases"]}
    review = stage_phase_id(client, pid, stage["id"], "Review", headers)
    assert review in blocked
    refused = client.post(
        _url(pid, f"components/{component['id']}/stages/{stage['id']}/transition"), json={"phase_id": review}, headers=headers,
    )
    assert refused.status_code == 409, refused.text
    approved = stage_phase_id(client, pid, stage["id"], "Approved", headers)
    assert approved not in blocked
    accepted = client.post(
        _url(pid, f"components/{component['id']}/stages/{stage['id']}/transition"), json={"phase_id": approved}, headers=headers,
    )
    assert accepted.status_code == 200, accepted.text


def _statements(client, token, project_id) -> int:
    counted: list[int] = []

    def count(*_args) -> None:
        counted.append(1)

    event.listen(engine, "before_cursor_execute", count)
    try:
        assert client.get(_url(project_id, "stages"), headers=auth_headers(token)).status_code == 200
        assert client.get(_url(project_id, "component-stages"), headers=auth_headers(token)).status_code == 200
    finally:
        event.remove(engine, "before_cursor_execute", count)
    return len(counted)


def test_the_statement_count_does_not_grow_with_stages_or_components(client, admin_token):
    _, project, token = _setup(client, admin_token, "Allowed Phases Flat Co")
    pid = project["id"]
    _component_with_tracks(client, token, pid)
    _disable(client, token, pid, "project_stage", ["review"])
    _disable(client, token, pid, "component_stage", ["review"])
    client.post(_url(pid, "stages"), json={"name": "Second"}, headers=auth_headers(token))
    small = _statements(client, token, pid)
    for index in range(2, 6):
        client.post(_url(pid, "components"), json={"name": f"Part {index}", "prefix": f"P{index}"}, headers=auth_headers(token))
        client.post(_url(pid, "stages"), json={"name": f"Stage {index}"}, headers=auth_headers(token))
    large = _statements(client, token, pid)
    assert large == small, (small, large)
