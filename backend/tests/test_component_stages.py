"""Component phases: the project switch (and ancestor inheritance), a component's own track per stage, what a
component's locked phase approves, how the stage's own lock leaves tracked components alone, who may move a
track, advisory progression, workflow and applicability rules, and bundles and template cloning."""

import io
import zipfile

from tests.conftest import auth_headers, create_org_user, create_project, create_project_group, login
from tests.stage_helpers import move_stage

OUTSOURCED = {
    "name": "Outsourced work",
    "phases": [
        {"name": "Scoping", "kind": "open"},
        {"name": "Review board", "kind": "review"},
        {"name": "Awarded", "kind": "locked"},
        {"name": "Completion", "kind": "closed"},
    ],
}


def _url(project_id: str, tail: str = "") -> str:
    return f"/api/v1/projects/{project_id}/{tail}"


def _stages(client, token, project_id) -> list[dict]:
    return client.get(_url(project_id, "stages"), headers=auth_headers(token)).json()


def _components(client, token, project_id) -> list[dict]:
    return client.get(_url(project_id, "components"), headers=auth_headers(token)).json()


def _workflow(client, token, project_id, name="Standard") -> dict:
    workflows = client.get(_url(project_id, "stage-workflows"), headers=auth_headers(token)).json()
    return next(w for w in workflows if w["name"] == name)


def _phase_id(workflow: dict, name: str) -> str:
    return next(p["id"] for p in workflow["phases"] if p["name"] == name)


def _turn_on(client, token, project_id) -> None:
    resp = client.put(_url(project_id, "component-phases-settings"), json={"mode": "on"}, headers=auth_headers(token))
    assert resp.status_code == 200, resp.text


def _move(client, token, project_id, component_id, stage_id, workflow: dict, phase: str):
    return client.post(
        _url(project_id, f"components/{component_id}/stages/{stage_id}/transition"),
        json={"phase_id": _phase_id(workflow, phase)}, headers=auth_headers(token),
    )


def _track(client, token, project_id, component_id, stage_id) -> dict:
    tracks = client.get(_url(project_id, "component-stages"), headers=auth_headers(token)).json()["tracks"]
    return next(t for t in tracks if t["component_id"] == component_id and t["stage_id"] == stage_id)


def _world(client, token, org_id):
    """A project with two components and two stages, one requirement per component and stage."""
    project = create_project(client, token, org_id)
    headers = auth_headers(token)
    first = client.post(_url(project["id"], "components"), json={"name": "Software", "prefix": "SW"}, headers=headers).json()
    second = client.post(_url(project["id"], "components"), json={"name": "Hardware", "prefix": "HW"}, headers=headers).json()
    categories = {}
    for component in (first, second):
        categories[component["id"]] = client.post(
            _url(project["id"], "categories"), json={"name": "General", "prefix": "GEN", "component_id": component["id"]},
            headers=headers,
        ).json()["id"]
    stage_one = _stages(client, token, project["id"])[0]
    stage_two = client.post(_url(project["id"], "stages"), json={"name": "Release 2"}, headers=headers).json()
    requirements = {}
    for component in (first, second):
        for stage in (stage_one, stage_two):
            created = client.post(
                _url(project["id"], "requirements"),
                json={"name": f"{component['prefix']} {stage['name']}", "component_id": component["id"],
                      "category_id": categories[component["id"]], "target_stage_id": stage["id"]},
                headers=headers,
            )
            assert created.status_code == 201, created.text
            requirements[(component["id"], stage["id"])] = created.json()["id"]
    return project, first, second, stage_one, stage_two, requirements


def _status(client, token, project_id, requirement_id) -> str:
    return client.get(_url(project_id, f"requirements/{requirement_id}"), headers=auth_headers(token)).json()["status"]


def test_component_phases_are_off_until_switched_on(client, admin_token, org_id):
    project, first, _second, stage_one, _stage_two, _reqs = _world(client, admin_token, org_id)
    headers = auth_headers(admin_token)
    state = client.get(_url(project["id"], "component-stages"), headers=headers).json()
    assert (state["mode"], state["own_mode"], state["tracks"]) == ("off", None, [])
    standard = _workflow(client, admin_token, project["id"])
    assert _move(client, admin_token, project["id"], first["id"], stage_one["id"], standard, "Review").status_code == 409
    changed = client.patch(
        _url(project["id"], f"components/{first['id']}/stages/{stage_one['id']}/track"), json={"not_applicable": True}, headers=headers,
    )
    assert changed.status_code == 409


def test_the_switch_is_set_by_managers_and_inherits_from_an_ancestor(client, admin_token, org_id):
    parent = create_project(client, admin_token, org_id, name="Parent", can_be_parent=True)
    child = create_project(client, admin_token, org_id, name="Child", parent_project_id=parent["id"])
    headers = auth_headers(admin_token)
    _turn_on(client, admin_token, parent["id"])
    inherited = client.get(_url(child["id"], "component-stages"), headers=headers).json()
    assert (inherited["mode"], inherited["own_mode"], inherited["inherited"]) == ("on", None, True)
    own_off = client.put(_url(child["id"], "component-phases-settings"), json={"mode": "off"}, headers=headers).json()
    assert (own_off["mode"], own_off["own_mode"], own_off["inherited"]) == ("off", "off", False)
    back = client.put(_url(child["id"], "component-phases-settings"), json={"mode": None}, headers=headers).json()
    assert (back["mode"], back["inherited"]) == ("on", True)

    create_org_user(client, admin_token, org_id, "member@example.com")
    users = client.get(f"/api/v1/orgs/{org_id}/users", headers=headers).json()
    user_id = next(u["user_id"] for u in users if u["email"] == "member@example.com")
    client.post(_url(parent["id"], "roles"), json={"user_id": user_id, "role": "member"}, headers=headers)
    member = login(client, "member@example.com", "Password123!")
    assert client.put(
        _url(parent["id"], "component-phases-settings"), json={"mode": "off"}, headers=auth_headers(member),
    ).status_code == 403


def test_every_component_has_a_track_per_stage_that_defaults_to_the_stage_workflow(client, admin_token, org_id):
    project, first, second, stage_one, stage_two, _reqs = _world(client, admin_token, org_id)
    _turn_on(client, admin_token, project["id"])
    tracks = client.get(_url(project["id"], "component-stages"), headers=auth_headers(admin_token)).json()["tracks"]
    assert len(tracks) == 4
    assert {(t["phase_name"], t["customised"], t["can_move"]) for t in tracks} == {("Scoping", False, True)}
    assert {t["component_id"] for t in tracks} == {first["id"], second["id"]}
    assert {t["stage_id"] for t in tracks} == {stage_one["id"], stage_two["id"]}


def test_a_component_lock_approves_only_that_component_for_that_stage(client, admin_token, org_id):
    project, first, second, stage_one, stage_two, reqs = _world(client, admin_token, org_id)
    _turn_on(client, admin_token, project["id"])
    standard = _workflow(client, admin_token, project["id"])
    moved = _move(client, admin_token, project["id"], first["id"], stage_one["id"], standard, "Approved")
    assert moved.status_code == 200, moved.text
    track = _track(client, admin_token, project["id"], first["id"], stage_one["id"])
    assert (track["phase_name"], track["customised"]) == ("Approved", True) and track["approved_at"] is not None

    states = {key: _status(client, admin_token, project["id"], rid) for key, rid in reqs.items()}
    assert states[(first["id"], stage_one["id"])] == "approved"
    assert states[(first["id"], stage_two["id"])] == "draft"
    assert states[(second["id"], stage_one["id"])] == "draft"
    assert states[(second["id"], stage_two["id"])] == "draft"
    # The stage's progress counts what its components' baselines captured: one requirement so far.
    metrics = client.get(_url(project["id"], "metrics"), headers=auth_headers(admin_token)).json()
    progress = {p["stage_id"]: p["requirement_count"] for p in metrics["stage_progress"]}
    assert progress[stage_one["id"]] == 1

    # Leaving the locked phase clears the stamp; the requirement stays approved (a baseline is history).
    back = _move(client, admin_token, project["id"], first["id"], stage_one["id"], standard, "Scoping")
    assert back.status_code == 200
    assert _track(client, admin_token, project["id"], first["id"], stage_one["id"])["approved_at"] is None
    assert _status(client, admin_token, project["id"], reqs[(first["id"], stage_one["id"])]) == "approved"


def test_the_stage_lock_leaves_components_with_their_own_track(client, admin_token, org_id):
    project, first, second, stage_one, _stage_two, reqs = _world(client, admin_token, org_id)
    _turn_on(client, admin_token, project["id"])
    standard = _workflow(client, admin_token, project["id"])
    # Software gets a track for the first stage (moved within open phases); Hardware does not.
    assert _move(client, admin_token, project["id"], first["id"], stage_one["id"], standard, "Review").status_code == 200
    assert move_stage(client, project["id"], stage_one["id"], "approved", headers=auth_headers(admin_token)).status_code == 200
    assert _status(client, admin_token, project["id"], reqs[(first["id"], stage_one["id"])]) == "draft"
    assert _status(client, admin_token, project["id"], reqs[(second["id"], stage_one["id"])]) == "approved"


def test_a_not_applicable_component_follows_the_stage_lock(client, admin_token, org_id):
    project, first, _second, stage_one, _stage_two, reqs = _world(client, admin_token, org_id)
    _turn_on(client, admin_token, project["id"])
    headers = auth_headers(admin_token)
    patched = client.patch(
        _url(project["id"], f"components/{first['id']}/stages/{stage_one['id']}/track"), json={"not_applicable": True}, headers=headers,
    )
    assert patched.status_code == 200, patched.text
    assert _track(client, admin_token, project["id"], first["id"], stage_one["id"])["not_applicable"] is True
    standard = _workflow(client, admin_token, project["id"])
    assert _move(client, admin_token, project["id"], first["id"], stage_one["id"], standard, "Review").status_code == 409
    assert move_stage(client, project["id"], stage_one["id"], "approved", headers=headers).status_code == 200
    assert _status(client, admin_token, project["id"], reqs[(first["id"], stage_one["id"])]) == "approved"


def test_switching_off_leaves_the_stage_in_charge_again(client, admin_token, org_id):
    project, first, _second, stage_one, _stage_two, reqs = _world(client, admin_token, org_id)
    _turn_on(client, admin_token, project["id"])
    standard = _workflow(client, admin_token, project["id"])
    _move(client, admin_token, project["id"], first["id"], stage_one["id"], standard, "Review")
    client.put(_url(project["id"], "component-phases-settings"), json={"mode": "off"}, headers=auth_headers(admin_token))
    assert move_stage(client, project["id"], stage_one["id"], "approved", headers=auth_headers(admin_token)).status_code == 200
    assert _status(client, admin_token, project["id"], reqs[(first["id"], stage_one["id"])]) == "approved"


def test_progression_is_advisory(client, admin_token, org_id):
    project, first, _second, stage_one, stage_two, _reqs = _world(client, admin_token, org_id)
    _turn_on(client, admin_token, project["id"])
    standard = _workflow(client, admin_token, project["id"])
    assert _track(client, admin_token, project["id"], first["id"], stage_two["id"])["previous_closed"] is False
    # The second stage can start before the first has closed.
    assert _move(client, admin_token, project["id"], first["id"], stage_two["id"], standard, "Review").status_code == 200
    assert _move(client, admin_token, project["id"], first["id"], stage_one["id"], standard, "Completed").status_code == 200
    track = _track(client, admin_token, project["id"], first["id"], stage_two["id"])
    assert track["previous_closed"] is True and track["phase_name"] == "Review"
    assert _track(client, admin_token, project["id"], first["id"], stage_one["id"])["completed_at"] is not None


def test_a_closed_track_can_complete_that_components_approved_requirements(client, admin_token, org_id):
    project, first, second, stage_one, _stage_two, reqs = _world(client, admin_token, org_id)
    _turn_on(client, admin_token, project["id"])
    headers = auth_headers(admin_token)
    standard = _workflow(client, admin_token, project["id"])
    _move(client, admin_token, project["id"], first["id"], stage_one["id"], standard, "Approved")
    _move(client, admin_token, project["id"], second["id"], stage_one["id"], standard, "Approved")
    resp = client.post(
        _url(project["id"], f"components/{first['id']}/stages/{stage_one['id']}/transition"),
        json={"phase_id": _phase_id(standard, "Completed"), "cascade_to_requirements": True}, headers=headers,
    )
    assert resp.status_code == 200, resp.text
    done = client.get(_url(project["id"], f"requirements/{reqs[(first['id'], stage_one['id'])]}"), headers=headers).json()
    other = client.get(_url(project["id"], f"requirements/{reqs[(second['id'], stage_one['id'])]}"), headers=headers).json()
    assert done["is_completed"] is True and other["is_completed"] is False


def test_a_track_follows_a_chosen_workflow_only_while_open_and_baseline_free(client, admin_token, org_id):
    project, first, _second, stage_one, _stage_two, _reqs = _world(client, admin_token, org_id)
    _turn_on(client, admin_token, project["id"])
    headers = auth_headers(admin_token)
    outsourced = client.post(f"/api/v1/orgs/{org_id}/stage-workflows", json=OUTSOURCED, headers=headers).json()
    url = _url(project["id"], f"components/{first['id']}/stages/{stage_one['id']}/track")
    assert client.patch(url, json={"workflow_id": outsourced["id"]}, headers=headers).status_code == 200
    track = _track(client, admin_token, project["id"], first["id"], stage_one["id"])
    assert (track["workflow_name"], track["phase_name"]) == ("Outsourced work", "Scoping")
    assert client.patch(url, json={"workflow_id": "00000000-0000-0000-0000-000000000000"}, headers=headers).status_code == 400

    assert _move(client, admin_token, project["id"], first["id"], stage_one["id"], outsourced, "Awarded").status_code == 200
    assert client.patch(url, json={"workflow_id": None}, headers=headers).status_code == 409
    assert client.patch(url, json={"not_applicable": True}, headers=headers).status_code == 409
    # The phase of another workflow is refused.
    standard = _workflow(client, admin_token, project["id"])
    assert _move(client, admin_token, project["id"], first["id"], stage_one["id"], standard, "Review").status_code == 400


def test_a_workflow_or_phase_in_use_by_a_track_cannot_be_removed(client, admin_token, org_id):
    project, first, _second, stage_one, _stage_two, _reqs = _world(client, admin_token, org_id)
    _turn_on(client, admin_token, project["id"])
    headers = auth_headers(admin_token)
    outsourced = client.post(f"/api/v1/orgs/{org_id}/stage-workflows", json=OUTSOURCED, headers=headers).json()
    client.patch(
        _url(project["id"], f"components/{first['id']}/stages/{stage_one['id']}/track"),
        json={"workflow_id": outsourced["id"]}, headers=headers,
    )
    assert client.delete(f"/api/v1/orgs/{org_id}/stage-workflows/{outsourced['id']}", headers=headers).status_code == 409
    kept = [{"id": p["id"], "name": p["name"], "kind": p["kind"]} for p in outsourced["phases"] if p["name"] != "Scoping"]
    trimmed = {"name": "Outsourced work", "phases": kept}
    assert client.put(f"/api/v1/orgs/{org_id}/stage-workflows/{outsourced['id']}", json=trimmed, headers=headers).status_code == 409


def _member(client, admin_token, org_id, project_id, email) -> tuple[str, str]:
    user_id = create_org_user(client, admin_token, org_id, email)
    resp = client.post(_url(project_id, "roles"), json={"user_id": user_id, "role": "member"}, headers=auth_headers(admin_token))
    assert resp.status_code in (200, 201, 204), resp.text
    return user_id, login(client, email, "Password123!")


def test_the_owner_may_move_the_track_including_into_a_locked_phase(client, admin_token, org_id):
    project, first, second, stage_one, _stage_two, reqs = _world(client, admin_token, org_id)
    _turn_on(client, admin_token, project["id"])
    headers = auth_headers(admin_token)
    owner_id, owner_token = _member(client, admin_token, org_id, project["id"], "owner@example.com")
    _other_id, other_token = _member(client, admin_token, org_id, project["id"], "other@example.com")
    standard = _workflow(client, admin_token, project["id"])
    url = _url(project["id"], f"components/{first['id']}/stages/{stage_one['id']}/track")

    # Only a manager names the owner.
    assert client.patch(url, json={"owner": {"type": "user", "id": owner_id}}, headers=auth_headers(owner_token)).status_code == 403
    assert client.patch(url, json={"owner": {"type": "user", "id": owner_id}}, headers=headers).status_code == 200
    mine = _track(client, owner_token, project["id"], first["id"], stage_one["id"])
    assert mine["can_move"] is True and mine["owner"]["label"] == "owner"
    assert _track(client, other_token, project["id"], first["id"], stage_one["id"])["can_move"] is False

    assert _move(client, other_token, project["id"], first["id"], stage_one["id"], standard, "Review").status_code == 403
    assert _move(client, owner_token, project["id"], first["id"], stage_one["id"], standard, "Review").status_code == 200
    assert _move(client, owner_token, project["id"], first["id"], stage_one["id"], standard, "Approved").status_code == 200
    assert _status(client, admin_token, project["id"], reqs[(first["id"], stage_one["id"])]) == "approved"
    # The owner has no say over another component's track.
    assert _move(client, owner_token, project["id"], second["id"], stage_one["id"], standard, "Review").status_code == 403


def test_a_group_may_own_a_track_and_its_members_may_move_it(client, admin_token, org_id):
    project, first, _second, stage_one, _stage_two, _reqs = _world(client, admin_token, org_id)
    _turn_on(client, admin_token, project["id"])
    headers = auth_headers(admin_token)
    member_id, member_token = _member(client, admin_token, org_id, project["id"], "team@example.com")
    _outsider_id, outsider_token = _member(client, admin_token, org_id, project["id"], "outsider@example.com")
    group_id = create_project_group(client, admin_token, project["id"], "Delivery team", users=[member_id])
    url = _url(project["id"], f"components/{first['id']}/stages/{stage_one['id']}/track")
    assert client.patch(url, json={"owner": {"type": "project_group", "id": group_id}}, headers=headers).status_code == 200
    standard = _workflow(client, admin_token, project["id"])
    assert _move(client, member_token, project["id"], first["id"], stage_one["id"], standard, "Review").status_code == 200
    assert _move(client, outsider_token, project["id"], first["id"], stage_one["id"], standard, "Scoping").status_code == 403
    # An owner from outside the organisation is refused, and the owner can be cleared.
    assert client.patch(url, json={"owner": {"type": "user", "id": "00000000-0000-0000-0000-000000000000"}}, headers=headers).status_code == 400
    cleared = client.patch(url, json={"owner": None}, headers=headers)
    assert cleared.status_code == 200
    assert _track(client, admin_token, project["id"], first["id"], stage_one["id"])["owner"] is None


def test_a_project_group_that_owns_a_track_cannot_be_deleted_silently(client, admin_token, org_id):
    project, first, _second, stage_one, _stage_two, _reqs = _world(client, admin_token, org_id)
    _turn_on(client, admin_token, project["id"])
    headers = auth_headers(admin_token)
    group_id = create_project_group(client, admin_token, project["id"], "Delivery team")
    client.patch(
        _url(project["id"], f"components/{first['id']}/stages/{stage_one['id']}/track"),
        json={"owner": {"type": "project_group", "id": group_id}}, headers=headers,
    )
    usage = client.get(_url(project["id"], f"groups/{group_id}/usage"), headers=headers)
    assert usage.status_code == 200, usage.text
    assert any("component stage owners" in item["label"] for item in usage.json()["items"])


def test_tracks_and_the_switch_round_trip_through_the_project_bundle(client, admin_token, org_id):
    project, first, _second, stage_one, _stage_two, _reqs = _world(client, admin_token, org_id)
    _turn_on(client, admin_token, project["id"])
    headers = auth_headers(admin_token)
    outsourced = client.post(f"/api/v1/orgs/{org_id}/stage-workflows", json=OUTSOURCED, headers=headers).json()
    client.patch(
        _url(project["id"], f"components/{first['id']}/stages/{stage_one['id']}/track"),
        json={"workflow_id": outsourced["id"]}, headers=headers,
    )
    assert _move(client, admin_token, project["id"], first["id"], stage_one["id"], outsourced, "Review board").status_code == 200
    # A second track is locked and component-baselined: it comes back at the start with a warning.
    standard = _workflow(client, admin_token, project["id"])
    other = _components(client, admin_token, project["id"])[1]
    assert _move(client, admin_token, project["id"], other["id"], stage_one["id"], standard, "Approved").status_code == 200

    export = client.get(_url(project["id"], "export"), headers=headers)
    assert b"component_stage_states" in zipfile.ZipFile(io.BytesIO(export.content)).read("project.json")
    imported = client.post(
        "/api/v1/projects/import", data={"organization_id": org_id, "name": "Tracks copy"},
        files={"file": ("bundle.zip", export.content, "application/zip")}, headers=headers,
    )
    assert imported.status_code == 201, imported.text
    assert any("Approved" in w for w in imported.json()["warnings"])
    new_id = imported.json()["project"]["id"]
    state = client.get(_url(new_id, "component-stages"), headers=headers).json()
    assert (state["mode"], state["own_mode"]) == ("on", "on")
    new_components = {c["prefix"]: c["id"] for c in _components(client, admin_token, new_id)}
    new_stage = _stages(client, admin_token, new_id)[0]
    copied = _track(client, admin_token, new_id, new_components["SW"], new_stage["id"])
    assert (copied["workflow_name"], copied["phase_name"], copied["customised"]) == ("Outsourced work", "Review board", True)
    reset = _track(client, admin_token, new_id, new_components["HW"], new_stage["id"])
    assert (reset["phase_name"], reset["approved_at"]) == ("Scoping", None)


def test_a_template_clone_copies_the_switch_and_workflow_choices_but_not_progress(client, admin_token, org_id):
    template, first, _second, stage_one, _stage_two, _reqs = _world(client, admin_token, org_id)
    headers = auth_headers(admin_token)
    _turn_on(client, admin_token, template["id"])
    outsourced = client.post(f"/api/v1/orgs/{org_id}/stage-workflows", json=OUTSOURCED, headers=headers).json()
    client.patch(
        _url(template["id"], f"components/{first['id']}/stages/{stage_one['id']}/track"),
        json={"workflow_id": outsourced["id"]}, headers=headers,
    )
    _move(client, admin_token, template["id"], first["id"], stage_one["id"], outsourced, "Review board")
    client.patch(_url(template["id"]), json={"is_template": True}, headers=headers)

    resp = client.post(
        "/api/v1/projects", json={"organization_id": org_id, "name": "From template", "summary": "", "template_project_id": template["id"]},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    new_id = resp.json()["id"]
    assert client.get(_url(new_id, "component-stages"), headers=headers).json()["mode"] == "on"
    new_components = {c["prefix"]: c["id"] for c in _components(client, admin_token, new_id)}
    new_stage = _stages(client, admin_token, new_id)[0]
    track = _track(client, admin_token, new_id, new_components["SW"], new_stage["id"])
    assert (track["workflow_name"], track["phase_name"]) == ("Outsourced work", "Scoping")


def test_the_requirement_list_shows_and_filters_by_the_governing_phase(client, admin_token, org_id):
    headers = auth_headers(admin_token)
    project, first, second, stage_one, _stage_two, requirements = _world(client, admin_token, org_id)
    listing = lambda **params: client.get(_url(project["id"], "requirements"), params=params, headers=headers).json()  # noqa: E731
    phase_of = lambda rows: {r["id"]: r["phase_name"] for r in rows}  # noqa: E731

    # Component phases off: every requirement is governed by its stage's phase.
    assert set(phase_of(listing(target_stage_id=stage_one["id"])).values()) == {"Scoping"}
    assert len(listing(phase="scoping")) == 4 and listing(phase="Review") == []

    # On, with one component's track moved: its requirements read that track's phase, the other component's the stage's.
    _turn_on(client, admin_token, project["id"])
    workflow = _workflow(client, admin_token, project["id"])
    assert _move(client, admin_token, project["id"], first["id"], stage_one["id"], workflow, "Review").status_code == 200
    by_phase = phase_of(listing(target_stage_id=stage_one["id"]))
    assert by_phase[requirements[(first["id"], stage_one["id"])]] == "Review"
    assert by_phase[requirements[(second["id"], stage_one["id"])]] == "Scoping"
    assert [r["id"] for r in listing(phase="review")] == [requirements[(first["id"], stage_one["id"])]]
    # The unmoved component's requirements are still governed by the stage's own phase.
    assert requirements[(second["id"], stage_one["id"])] in [r["id"] for r in listing(phase="Scoping")]
    assert requirements[(first["id"], stage_one["id"])] not in [r["id"] for r in listing(phase="Scoping")]

    # Not applicable: no governing phase, and the requirement matches no phase filter.
    client.patch(
        _url(project["id"], f"components/{second['id']}/stages/{stage_one['id']}/track"), json={"not_applicable": True}, headers=headers,
    )
    rows = {r["id"]: r for r in listing(target_stage_id=stage_one["id"])}
    assert rows[requirements[(second["id"], stage_one["id"])]]["phase_name"] is None
    assert requirements[(second["id"], stage_one["id"])] not in [r["id"] for r in listing(phase="Scoping")]
