"""Tests for state machine diagrams and their states and transitions: creation and codes, the Architect gate, the
lifecycle and the version lock, the activation gate (errors refuse it, warnings never do, and a refused Save and
activate stores nothing), nesting rules, deleting a state with its transitions and links, an element another project shares
(and a hidden one answering 404 on every read path), the project-wide States list, search, summaries and the audit trail.
Every test builds its own organisation."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.database import SessionLocal
from app.models.audit import AuditEvent
from app.modules.architecture.models import ArchitectureStateMachineDiagram
from app.modules.architecture.tests._helpers import (
    add_member,
    add_state,
    add_transition,
    grant,
    machine_model,
    machine_version,
    make_architect,
    make_collection,
    make_element,
    make_machine,
    move_status,
    project_base,
    setup,
    sound_machine,
)
from app.modules.registry import get_artefact_summaries_in_project
from tests.conftest import auth_headers, create_project
from tests.link_world import World

MACHINE = "architecture_state_machine_diagram"
STATE = "architecture_state"


def _machines(client, token, project_id, **params) -> list[dict]:
    resp = client.get(f"{project_base(project_id)}/state-machine-diagrams", params=params, headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return resp.json()


def _states(client, token, project_id, **params) -> list[dict]:
    resp = client.get(f"{project_base(project_id)}/states", params=params, headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return resp.json()


def _audit_actions(entity_type: str, entity_id: str) -> list[str]:
    with SessionLocal() as db:
        return [
            e.action for e in db.scalars(
                select(AuditEvent).where(AuditEvent.entity_type == entity_type, AuditEvent.entity_id == entity_id)
                .order_by(AuditEvent.created_at)
            )
        ]


# --- The record ----------------------------------------------------------------


def test_a_state_machine_diagram_is_created_as_a_draft_with_a_code_and_its_states_have_their_own(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch smd create")
    element = make_element(client, token, project["id"], "Flight controller")
    machine = make_machine(client, token, project["id"], element["id"], "Operating modes", description="Modes of flight.")
    assert machine["unique_code"] == "SMD-001" and machine["status"] == "draft" and machine["version"] == 1
    assert machine["element_code"] == element["unique_code"] and machine["element_name"] == "Flight controller"
    assert (machine["state_count"], machine["transition_count"]) == (0, 0)
    second = make_machine(client, token, project["id"], element["id"], "Fault handling")
    assert second["unique_code"] == "SMD-002"  # one element may have several
    start = add_state(client, token, project["id"], machine["id"], "Start", kind="initial")
    idle = add_state(client, token, project["id"], machine["id"], "Idle")
    other = add_state(client, token, project["id"], second["id"], "Start", kind="initial")  # a name is unique per diagram only
    assert [start["unique_code"], idle["unique_code"], other["unique_code"]] == ["STE-001", "STE-002", "STE-003"]
    assert start["state_machine_diagram_code"] == "SMD-001" and start["element_code"] == element["unique_code"]
    shown = client.get(f"{project_base(project['id'])}/state-machine-diagrams/{machine['id']}", headers=auth_headers(token)).json()
    assert shown["state_count"] == 2 and shown["version"] == 3


def test_a_duplicate_state_name_in_one_diagram_is_refused_without_regard_to_case(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch smd names")
    element = make_element(client, token, project["id"], "Pump")
    machine = make_machine(client, token, project["id"], element["id"])
    add_state(client, token, project["id"], machine["id"], "Idle")
    add_state(client, token, project["id"], machine["id"], "idle", expect=400)


def test_only_an_architect_may_change_a_state_machine_diagram_but_any_member_reads_it(client, admin_token):
    org, project, token = setup(client, admin_token, "Arch smd gate")
    element = make_element(client, token, project["id"], "Valve")
    machine, states = sound_machine(client, token, project["id"], element["id"])
    _uid, member = add_member(client, token, org["id"], project["id"], "arch.smd.member@example.com")
    architect = make_architect(client, token, org["id"], project["id"], "arch.smd.architect@example.com")
    base = project_base(project["id"])
    version = machine_version(client, token, project["id"], machine["id"])
    assert client.get(f"{base}/state-machine-diagrams/{machine['id']}/model", headers=auth_headers(member)).status_code == 200
    assert _states(client, member, project["id"])
    denied = [
        client.post(f"{base}/state-machine-diagrams", json={"name": "No", "element_id": element["id"]}, headers=auth_headers(member)),
        client.put(f"{base}/state-machine-diagrams/{machine['id']}", json={"version": version, "name": "No"}, headers=auth_headers(member)),
        client.post(f"{base}/state-machine-diagrams/{machine['id']}/states", json={"version": version, "name": "No"}, headers=auth_headers(member)),
        client.put(f"{base}/states/{states['Running']['id']}", json={"version": version, "name": "No"}, headers=auth_headers(member)),
        client.delete(f"{base}/states/{states['Running']['id']}", params={"version": version}, headers=auth_headers(member)),
        client.delete(f"{base}/state-machine-diagrams/{machine['id']}", headers=auth_headers(member)),
    ]
    assert [r.status_code for r in denied] == [403] * len(denied)
    assert make_machine(client, architect, project["id"], element["id"], "By an architect")["unique_code"] == "SMD-002"


def test_a_stale_version_is_refused_and_every_change_advances_it(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch smd lock")
    element = make_element(client, token, project["id"], "Motor")
    machine = make_machine(client, token, project["id"], element["id"])
    base = project_base(project["id"])
    state = add_state(client, token, project["id"], machine["id"], "Start", kind="initial")
    stale = client.post(
        f"{base}/state-machine-diagrams/{machine['id']}/states", json={"version": machine["version"], "name": "Late"},
        headers=auth_headers(token),
    )
    assert stale.status_code == 409
    assert client.put(
        f"{base}/states/{state['id']}", json={"version": machine["version"], "name": "Late"}, headers=auth_headers(token),
    ).status_code == 409
    current = machine_version(client, token, project["id"], machine["id"])
    renamed = client.put(f"{base}/states/{state['id']}", json={"version": current, "name": "Begin"}, headers=auth_headers(token))
    assert renamed.status_code == 200 and renamed.json()["state_machine_diagram_version"] == current + 1
    edited = client.put(
        f"{base}/state-machine-diagrams/{machine['id']}", json={"version": current + 1, "name": "Renamed"}, headers=auth_headers(token),
    )
    assert edited.status_code == 200 and edited.json()["version"] == current + 2
    assert client.put(
        f"{base}/state-machine-diagrams/{machine['id']}", json={"version": current + 1, "name": "Again"}, headers=auth_headers(token),
    ).status_code == 409


def test_every_change_is_audited_with_ids_and_no_names(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch smd audit")
    element = make_element(client, token, project["id"], "Relay")
    machine, states = sound_machine(client, token, project["id"], element["id"])
    move_status(client, token, project["id"], machine["id"], "active")
    assert _audit_actions(MACHINE, machine["id"])[:1] == ["created"]
    actions = _audit_actions(MACHINE, machine["id"])
    assert "status_changed" in actions and actions.count("updated") == 5  # three states and two transitions
    assert _audit_actions(STATE, states["Running"]["id"]) == ["created"]
    with SessionLocal() as db:
        events = list(db.scalars(select(AuditEvent).where(AuditEvent.entity_id == states["Running"]["id"])))
        assert events and all("Running" not in str(e.detail) and "spin_up" not in str(e.detail) for e in events)


# --- The activation gate ---------------------------------------------------------


def test_activation_is_refused_with_an_error_and_allowed_with_only_warnings(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch smd gate activation")
    element = make_element(client, token, project["id"], "Thermostat")
    machine = make_machine(client, token, project["id"], element["id"])
    refused = move_status(client, token, project["id"], machine["id"], "active", expect=409)
    assert "initial state" in refused["detail"]
    start = add_state(client, token, project["id"], machine["id"], "Start", kind="initial")
    idle = add_state(client, token, project["id"], machine["id"], "Idle")
    add_transition(client, token, project["id"], machine["id"], start["id"], idle["id"])
    model = machine_model(client, token, project["id"], machine["id"])
    assert [f["code"] for f in model["findings"]] == ["no_outgoing"]  # a warning only
    assert (model["diagram"]["error_count"], model["diagram"]["warning_count"]) == (0, 1)
    assert move_status(client, token, project["id"], machine["id"], "active")["status"] == "active"


def test_save_and_activate_on_create_stores_nothing_when_the_checks_refuse_it(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch smd save activate")
    element = make_element(client, token, project["id"], "Heater")
    refused = make_machine(client, token, project["id"], element["id"], "Empty", activate=True, expect=409)
    assert "initial state" in refused["detail"]
    assert _machines(client, token, project["id"], include_archived="true") == []
    with SessionLocal() as db:
        stored = select(ArchitectureStateMachineDiagram.id).where(ArchitectureStateMachineDiagram.project_id == uuid.UUID(project["id"]))
        assert db.scalar(stored) is None


def test_an_edit_to_an_active_diagram_that_adds_an_error_is_saved_and_shown(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch smd repair")
    element = make_element(client, token, project["id"], "Fan")
    machine, states = sound_machine(client, token, project["id"], element["id"])
    move_status(client, token, project["id"], machine["id"], "active")
    # A second initial state makes an error; the edit is not refused, so the diagram can be repaired.
    added = add_state(client, token, project["id"], machine["id"], "Extra", kind="initial")
    model = machine_model(client, token, project["id"], machine["id"])
    assert model["diagram"]["status"] == "active" and model["diagram"]["error_count"] >= 1
    assert "multiple_initial" in {f["code"] for f in model["findings"]}
    version = machine_version(client, token, project["id"], machine["id"])
    base = project_base(project["id"])
    assert client.delete(f"{base}/states/{added['id']}", params={"version": version}, headers=auth_headers(token)).status_code == 200
    assert machine_model(client, token, project["id"], machine["id"])["diagram"]["error_count"] == 0
    # Retiring and reactivating runs the gate again.
    move_status(client, token, project["id"], machine["id"], "retired")
    assert move_status(client, token, project["id"], machine["id"], "active")["status"] == "active"
    assert states


# --- States and transitions ----------------------------------------------------


def test_nesting_needs_an_ordinary_parent_of_the_same_diagram_and_has_no_cycles(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch smd nesting")
    element = make_element(client, token, project["id"], "Engine")
    machine = make_machine(client, token, project["id"], element["id"])
    other = make_machine(client, token, project["id"], element["id"], "Other")
    base = project_base(project["id"])
    outer = add_state(client, token, project["id"], machine["id"], "Outer")
    inner = add_state(client, token, project["id"], machine["id"], "Inner", parent_state_id=outer["id"])
    assert inner["parent_state_code"] == outer["unique_code"]
    marker = add_state(client, token, project["id"], machine["id"], "Begin", kind="initial")
    add_state(client, token, project["id"], machine["id"], "Under a marker", parent_state_id=marker["id"], expect=400)
    foreign = add_state(client, token, project["id"], other["id"], "Elsewhere")
    add_state(client, token, project["id"], machine["id"], "Cross", parent_state_id=foreign["id"], expect=400)
    version = machine_version(client, token, project["id"], machine["id"])
    cycle = client.put(f"{base}/states/{outer['id']}", json={"version": version, "parent_state_id": inner["id"]}, headers=auth_headers(token))
    assert cycle.status_code == 400
    self_parent = client.put(f"{base}/states/{outer['id']}", json={"version": version, "parent_state_id": outer["id"]}, headers=auth_headers(token))
    assert self_parent.status_code == 400
    marked = client.put(f"{base}/states/{outer['id']}", json={"version": version, "kind": "final"}, headers=auth_headers(token))
    assert marked.status_code == 400  # a state holding another cannot become a marker
    moved = client.put(f"{base}/states/{inner['id']}", json={"version": version, "parent_state_id": None}, headers=auth_headers(token))
    assert moved.status_code == 200 and moved.json()["parent_state_id"] is None


def test_the_nesting_depth_is_capped(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch smd depth")
    element = make_element(client, token, project["id"], "Deep")
    machine = make_machine(client, token, project["id"], element["id"])
    parent_id = None
    for level in range(12):
        parent_id = add_state(client, token, project["id"], machine["id"], f"Level {level}", parent_state_id=parent_id)["id"]
    add_state(client, token, project["id"], machine["id"], "Too deep", parent_state_id=parent_id, expect=400)


def test_a_transition_joins_two_states_of_its_own_diagram_and_a_self_transition_is_allowed(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch smd transitions")
    element = make_element(client, token, project["id"], "Charger")
    machine = make_machine(client, token, project["id"], element["id"])
    other = make_machine(client, token, project["id"], element["id"], "Other")
    a = add_state(client, token, project["id"], machine["id"], "A")
    foreign = add_state(client, token, project["id"], other["id"], "B")
    loop = add_transition(client, token, project["id"], machine["id"], a["id"], a["id"], event="tick", guard="n < 3", action="n++")
    assert loop["source_state_code"] == loop["target_state_code"] == a["unique_code"] and loop["event"] == "tick"
    add_transition(client, token, project["id"], machine["id"], a["id"], foreign["id"], expect=400)
    base = project_base(project["id"])
    version = machine_version(client, token, project["id"], machine["id"])
    missing = client.post(
        f"{base}/state-machine-diagrams/{machine['id']}/transitions", json={"version": version, "source_state_id": a["id"]},
        headers=auth_headers(token),
    )
    assert missing.status_code == 400
    edited = client.put(
        f"{base}/state-machine-diagrams/{machine['id']}/transitions/{loop['id']}",
        json={"version": version, "event": "timeout", "source_point": "top", "target_point": "bottom"}, headers=auth_headers(token),
    )
    assert edited.status_code == 200 and edited.json()["source_point"] == "top" and edited.json()["guard"] == "n < 3"
    removed = client.delete(
        f"{base}/state-machine-diagrams/{machine['id']}/transitions/{loop['id']}", params={"version": version + 1},
        headers=auth_headers(token),
    )
    assert removed.status_code == 200 and removed.json()["version"] == version + 2
    assert machine_model(client, token, project["id"], machine["id"])["transitions"] == []


def test_deleting_a_state_removes_its_transitions_and_links_but_not_while_it_contains_states(client, admin_token):
    world = World(client, admin_token, "Arch smd delete state")
    world.enable("architecture")
    project = world.project("Arch smd delete state project")
    token = world.token
    element = make_element(client, token, project["id"], "Lift")
    machine, states = sound_machine(client, token, project["id"], element["id"])
    requirement = world.requirement(project)
    types = world.link_types_by_name()
    linked = world.generic_link(project, ("requirement", requirement), types["Allocated to"]["id"], (STATE, uuid.UUID(states["Running"]["id"])))
    assert linked.status_code in (200, 201), linked.text
    nested = add_state(client, token, project["id"], machine["id"], "Nested", parent_state_id=states["Running"]["id"])
    base = project_base(project["id"])
    impact = client.get(f"{base}/states/{states['Running']['id']}/impact", headers=auth_headers(token)).json()
    assert impact == {"transitions": 2, "links": 1}
    version = machine_version(client, token, project["id"], machine["id"])
    blocked = client.delete(f"{base}/states/{states['Running']['id']}", params={"version": version}, headers=auth_headers(token))
    assert blocked.status_code == 409
    assert client.delete(f"{base}/states/{nested['id']}", params={"version": version}, headers=auth_headers(token)).status_code == 200
    removed = client.delete(
        f"{base}/states/{states['Running']['id']}", params={"version": version + 1}, headers=auth_headers(token),
    )
    assert removed.status_code == 200 and (removed.json()["transitions"], removed.json()["links"]) == (2, 1)
    model = machine_model(client, token, project["id"], machine["id"])
    assert [s["name"] for s in model["states"]] == ["Start", "Stop"] and model["transitions"] == []
    assert client.get(f"{base}/states/{states['Running']['id']}", headers=auth_headers(token)).status_code == 404


def test_deleting_a_diagram_removes_its_states_transitions_and_their_links(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch smd delete machine")
    element = make_element(client, token, project["id"], "Crane")
    machine, states = sound_machine(client, token, project["id"], element["id"])
    base = project_base(project["id"])
    assert client.delete(f"{base}/state-machine-diagrams/{machine['id']}", headers=auth_headers(token)).status_code == 204
    assert _machines(client, token, project["id"], include_archived="true") == [] and _states(client, token, project["id"]) == []
    assert client.get(f"{base}/states/{states['Start']['id']}", headers=auth_headers(token)).status_code == 404
    # The element described is untouched, and its code is not reused.
    assert client.get(f"{base}/elements/{element['id']}", headers=auth_headers(token)).status_code == 200
    assert make_machine(client, token, project["id"], element["id"])["unique_code"] == "SMD-002"


def test_an_element_cannot_be_deleted_while_a_state_machine_diagram_describes_it(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch smd element delete")
    element = make_element(client, token, project["id"], "Door")
    machine = make_machine(client, token, project["id"], element["id"])
    base = project_base(project["id"])
    blocked = client.delete(f"{base}/elements/{element['id']}", headers=auth_headers(token))
    assert blocked.status_code == 409 and "state machine diagram" in blocked.json()["detail"]
    assert client.delete(f"{base}/state-machine-diagrams/{machine['id']}", headers=auth_headers(token)).status_code == 204
    assert client.delete(f"{base}/elements/{element['id']}", headers=auth_headers(token)).status_code == 204


def test_saving_a_layout_moves_boxes_and_nests_states_and_refuses_a_state_of_another_diagram(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch smd layout")
    element = make_element(client, token, project["id"], "Printer")
    machine, states = sound_machine(client, token, project["id"], element["id"])
    other = make_machine(client, token, project["id"], element["id"], "Other")
    stranger = add_state(client, token, project["id"], other["id"], "Alien")
    base = project_base(project["id"])
    version = machine_version(client, token, project["id"], machine["id"])
    transition_id = machine_model(client, token, project["id"], machine["id"])["transitions"][0]["id"]
    saved = client.put(f"{base}/state-machine-diagrams/{machine['id']}/layout", json={
        "version": version,
        "states": [{"id": states["Start"]["id"], "x": 10, "y": 20, "width": 40, "height": 40, "parent_state_id": states["Running"]["id"]}],
        "transitions": [{"id": transition_id, "source_point": "right", "target_point": "left"}],
    }, headers=auth_headers(token))
    assert saved.status_code == 200 and saved.json()["version"] == version + 1
    model = machine_model(client, token, project["id"], machine["id"])
    start = next(s for s in model["states"] if s["name"] == "Start")
    assert (start["x"], start["y"], start["parent_state_code"]) == (10, 20, states["Running"]["unique_code"])
    assert model["transitions"][0]["source_point"] == "right"
    layout = f"{base}/state-machine-diagrams/{machine['id']}/layout"
    again = client.put(layout, json={"version": version + 1, "states": [], "transitions": []}, headers=auth_headers(token))
    assert again.status_code == 200 and again.json()["version"] == version + 1  # nothing changed, nothing advanced
    for body in (
        {"states": [{"id": stranger["id"], "x": 0, "y": 0, "width": 10, "height": 10}], "transitions": []},
        {"states": [], "transitions": [{"id": str(uuid.uuid4())}]},
    ):
        refused = client.put(layout, json={"version": version + 1, **body}, headers=auth_headers(token))
        assert refused.status_code == 400
    stale = client.put(layout, json={"version": version, "states": [], "transitions": []}, headers=auth_headers(token))
    assert stale.status_code == 409


# --- Lists, filters, summaries and search -----------------------------------------


def test_the_lists_filter_and_the_states_list_spans_diagrams(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch smd lists")
    first = make_element(client, token, project["id"], "Pump")
    second = make_element(client, token, project["id"], "Valve")
    one, _ = sound_machine(client, token, project["id"], first["id"], "Pump modes")
    two = make_machine(client, token, project["id"], second["id"], "Valve modes")
    add_state(client, token, project["id"], two["id"], "Closed", activity="hold_shut()")
    move_status(client, token, project["id"], one["id"], "active")
    assert [m["name"] for m in _machines(client, token, project["id"])] == ["Pump modes", "Valve modes"]
    assert [m["name"] for m in _machines(client, token, project["id"], status="active")] == ["Pump modes"]
    assert [m["name"] for m in _machines(client, token, project["id"], element_id=second["id"])] == ["Valve modes"]
    assert [m["name"] for m in _machines(client, token, project["id"], search="valve")] == ["Valve modes"]
    assert len(_states(client, token, project["id"])) == 4
    assert [s["name"] for s in _states(client, token, project["id"], kind="final")] == ["Stop"]
    assert [s["name"] for s in _states(client, token, project["id"], search="hold_shut")] == ["Closed"]
    assert [s["name"] for s in _states(client, token, project["id"], state_machine_diagram_id=two["id"])] == ["Closed"]
    # Archiving takes a diagram, and so its states, out of the default lists.
    base = project_base(project["id"])
    assert client.post(f"{base}/state-machine-diagrams/{two['id']}/archive", headers=auth_headers(token)).status_code == 200
    assert [m["name"] for m in _machines(client, token, project["id"])] == ["Pump modes"]
    assert [s["name"] for s in _states(client, token, project["id"])] == ["Start", "Running", "Stop"]
    assert len(_states(client, token, project["id"], include_archived="true")) == 4


def test_a_diagram_and_a_state_are_found_by_the_global_search_and_comment_text_is_only_matched_on_request(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch smd search")
    element = make_element(client, token, project["id"], "Reactor")
    machine = make_machine(client, token, project["id"], element["id"], "Coolant modes", description="Quenching behaviour.")
    add_state(client, token, project["id"], machine["id"], "Quench", entry_action="open_valve()", activity="monitor_temp()")
    base = project_base(project["id"])
    assert client.post(
        f"{base}/state-machine-diagrams/{machine['id']}/comments", json={"body": "zebrafish remark"}, headers=auth_headers(token),
    ).status_code == 201

    def hits(text: str, fields: list[str]) -> list[tuple[str, str]]:
        resp = client.post(
            "/api/v1/search", json={"q": text, "scope": "project", "project_id": project["id"], "fields": fields}, headers=auth_headers(token),
        )
        assert resp.status_code == 200, resp.text
        return [(h["type"], h["title"]) for h in resp.json()["hits"] if h["type"] in (MACHINE, STATE)]

    everything = ["id", "title", "description", "entry_action", "exit_action", "activity"]
    assert hits("coolant", everything) == [(MACHINE, "Coolant modes")]
    assert hits("quenching", everything) == [(MACHINE, "Coolant modes")]
    assert hits("open_valve", everything) == [(STATE, "Quench")]
    assert hits("monitor_temp", ["activity"]) == [(STATE, "Quench")]
    assert hits("zebrafish", everything) == []
    assert hits("zebrafish", [*everything, "comments"]) == [(MACHINE, "Coolant modes")]


def test_the_summaries_label_a_diagram_and_a_state_by_code_and_follow_the_diagram_status(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch smd summaries")
    element = make_element(client, token, project["id"], "Boiler")
    machine, states = sound_machine(client, token, project["id"], element["id"], "Firing")
    move_status(client, token, project["id"], machine["id"], "active")
    with SessionLocal() as db:
        machine_id, state_id = uuid.UUID(machine["id"]), uuid.UUID(states["Running"]["id"])
        found = get_artefact_summaries_in_project(db, uuid.UUID(project["id"]), MACHINE, [machine_id]) or {}
        assert found[machine_id].label == f"{machine['unique_code']} Firing" and found[machine_id].status == "active"
        found = get_artefact_summaries_in_project(db, uuid.UUID(project["id"]), STATE, [state_id]) or {}
        assert found[state_id].label == f"{states['Running']['unique_code']} Running" and found[state_id].status == "active"


# --- Element visibility ----------------------------------------------------------


def test_another_project_s_ids_look_absent(client, admin_token):
    org, project, token = setup(client, admin_token, "Arch smd isolation")
    other = create_project(client, token, org["id"], "Arch smd isolation other")
    element = make_element(client, token, project["id"], "Gear")
    machine, states = sound_machine(client, token, project["id"], element["id"])
    base = project_base(other["id"])
    for path in (
        f"/state-machine-diagrams/{machine['id']}", f"/state-machine-diagrams/{machine['id']}/model",
        f"/state-machine-diagrams/{machine['id']}/comments", f"/states/{states['Start']['id']}",
    ):
        assert client.get(f"{base}{path}", headers=auth_headers(token)).status_code == 404, path
    assert _machines(client, token, other["id"]) == [] and _states(client, token, other["id"]) == []


def test_a_diagram_of_a_hidden_shared_element_answers_404_on_every_read_path(client, admin_token):
    org, owner, token = setup(client, admin_token, "Arch smd hidden")
    consumer = create_project(client, token, org["id"], "Arch smd hidden consumer")
    shared = make_element(client, token, owner["id"], "Platform")
    owner_base = project_base(owner["id"])
    collection = make_collection(client, token, owner_base, "Shared", members=[shared["id"]])
    given = grant(client, token, owner_base, collection["id"], project_id=consumer["id"])
    base = project_base(consumer["id"])
    # The organisation administrator can open the owning project, so the person who loses sight of the element is a
    # consumer-project architect with no access to the owner.
    architect = make_architect(client, token, org["id"], consumer["id"], "arch.smd.hidden@example.com")
    machine, states = sound_machine(client, architect, consumer["id"], shared["id"], "Platform modes")
    assert machine["element_code"] == shared["unique_code"] and machine["element_name"] == "Platform"
    assert client.delete(f"{owner_base}/collections/{collection['id']}/grants/{given['id']}", headers=auth_headers(token)).status_code == 204
    for path in (
        f"/state-machine-diagrams/{machine['id']}", f"/state-machine-diagrams/{machine['id']}/model",
        f"/state-machine-diagrams/{machine['id']}/comments", f"/states/{states['Running']['id']}",
        f"/states/{states['Running']['id']}/impact",
    ):
        assert client.get(f"{base}{path}", headers=auth_headers(architect)).status_code == 404, path
    version = 1
    writes = [
        client.put(f"{base}/state-machine-diagrams/{machine['id']}", json={"version": version, "name": "Leak"}, headers=auth_headers(architect)),
        client.post(
            f"{base}/state-machine-diagrams/{machine['id']}/states", json={"version": version, "name": "Leak"},
            headers=auth_headers(architect),
        ),
        client.post(
            f"{base}/state-machine-diagrams/{machine['id']}/status", json={"version": version, "status": "proposed"},
            headers=auth_headers(architect),
        ),
        client.delete(f"{base}/state-machine-diagrams/{machine['id']}", headers=auth_headers(architect)),
    ]
    assert [r.status_code for r in writes] == [404] * len(writes)
    assert _machines(client, architect, consumer["id"]) == [] and _states(client, architect, consumer["id"]) == []
    with SessionLocal() as db:
        assert not get_artefact_summaries_in_project(db, uuid.UUID(consumer["id"]), MACHINE, [uuid.UUID(machine["id"])])
        assert not get_artefact_summaries_in_project(db, uuid.UUID(consumer["id"]), STATE, [uuid.UUID(states["Start"]["id"])])
    hits = client.post(
        "/api/v1/search", json={"q": "Platform modes", "scope": "project", "project_id": consumer["id"], "fields": ["title"]},
        headers=auth_headers(architect),
    ).json()["hits"]
    assert [h for h in hits if h["type"] == MACHINE] == []
    # The owning project is unaffected, and restoring the grant brings the diagram back.
    assert _machines(client, architect, consumer["id"]) == []
    grant(client, token, owner_base, collection["id"], project_id=consumer["id"])
    assert [m["name"] for m in _machines(client, architect, consumer["id"])] == ["Platform modes"]


def test_a_new_diagram_cannot_name_an_element_the_person_cannot_read(client, admin_token):
    org, owner, token = setup(client, admin_token, "Arch smd unreadable")
    consumer = create_project(client, token, org["id"], "Arch smd unreadable consumer")
    private = make_element(client, token, owner["id"], "Private")
    architect = make_architect(client, token, org["id"], consumer["id"], "arch.smd.consumer@example.com")
    resp = client.post(
        f"{project_base(consumer['id'])}/state-machine-diagrams", json={"name": "No", "element_id": private["id"]}, headers=auth_headers(architect),
    )
    assert resp.status_code == 400
