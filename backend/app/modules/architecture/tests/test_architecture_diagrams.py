"""Tests for diagrams: creation and codes, the Architect gate, the lifecycle and the version lock, saving a layout and
single placements (an element is never deleted by unplacing it), view toggles (manual members, rules, saved defaults and
per-request overrides, bridging with its hops), roll-up and the internal-connection count, plain and detailed lines,
elements another project shares (and their locked placeholder after a revoke), the server SVG and its escaping, and the
audit trail. Every test builds its own organisation."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.database import SessionLocal
from app.models.audit import AuditEvent
from app.models.project import Project
from app.models.user import User
from app.modules.architecture.tests._helpers import (
    add_member,
    connection_types,
    element_types,
    grant,
    make_architect,
    make_collection,
    make_connection,
    make_diagram,
    make_element,
    place,
    place_all,
    project_base,
    save_toggles,
    setup,
    view,
)
from app.modules.registry import get_artefact_summaries_in_project
from app.services.record_tables import creatable_record_types
from tests.conftest import auth_headers, create_project


def _put(client, token, project_id, diagram, path, body, expect=200):
    resp = client.put(
        f"{project_base(project_id)}/diagrams/{diagram['id']}{path}", json={"version": diagram["version"], **body},
        headers=auth_headers(token),
    )
    assert resp.status_code == expect, resp.text
    return resp.json()


def _layout(diagram_view):
    return {n["unique_code"]: n for n in diagram_view["nodes"]}


# --- The record --------------------------------------------------------------


def test_the_links_panel_offers_to_create_a_diagram_only_to_an_architect(client, admin_token):
    org, project, token = setup(client, admin_token, "Arch diagram creatable")
    _uid, _member_token = add_member(client, token, org["id"], project["id"], "arch.diagram.plain@example.com")
    architect = make_architect(client, token, org["id"], project["id"], "arch.diagram.creator@example.com")
    assert architect
    with SessionLocal() as db:
        row = db.get(Project, uuid.UUID(project["id"]))
        plain = db.scalar(select(User).where(User.email == "arch.diagram.plain@example.com"))
        creator = db.scalar(select(User).where(User.email == "arch.diagram.creator@example.com"))
        assert row is not None and plain is not None and creator is not None
        assert "architecture_diagram" not in creatable_record_types(db, plain, row, ["architecture_diagram"])
        assert "architecture_diagram" in creatable_record_types(db, creator, row, ["architecture_diagram"])


def test_a_diagram_is_numbered_starts_draft_and_can_be_created_active(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch diagram create")
    first = make_diagram(client, token, project["id"], "System context", purpose="How it fits together.")
    second = make_diagram(client, token, project["id"], "Telemetry", activate=True, connection_detail=True)
    assert (first["unique_code"], first["status"], first["version"]) == ("DGM-001", "draft", 1)
    assert (second["unique_code"], second["status"], second["connection_detail"]) == ("DGM-002", "active", True)
    assert first["placement_count"] == first["note_count"] == first["toggle_count"] == 0
    listed = client.get(f"{project_base(project['id'])}/diagrams", headers=auth_headers(token)).json()
    assert [d["unique_code"] for d in listed] == ["DGM-001", "DGM-002"]


def test_populate_places_the_roots_or_the_scopes_children_on_a_grid(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch diagram populate")
    platform = make_element(client, token, project["id"], "Platform", type_name="System")
    make_element(client, token, project["id"], "Cloud", type_name="System")
    make_element(client, token, project["id"], "API", parent_id=platform["id"])
    make_element(client, token, project["id"], "Worker", parent_id=platform["id"])
    context = make_diagram(client, token, project["id"], "Context", populate=True)
    inside = make_diagram(client, token, project["id"], "Inside", populate=True, scope_element_id=platform["id"])
    assert context["placement_count"] == 2 and inside["placement_count"] == 2
    assert inside["scope_element_code"] == platform["unique_code"] and inside["scope_element_name"] == "Platform"
    names = {n["unique_code"]: n["name"] for n in view(client, token, project["id"], inside["id"])["nodes"]}
    assert sorted(names.values()) == ["API", "Worker"]


def test_only_an_architect_may_change_a_diagram_and_any_member_may_read_it(client, admin_token):
    org, project, token = setup(client, admin_token, "Arch diagram gate")
    h = auth_headers(token)
    diagram = make_diagram(client, token, project["id"], "Context")
    _uid, member = add_member(client, token, org["id"], project["id"], "arch.diagram.member@example.com")
    base = project_base(project["id"])
    assert client.get(f"{base}/diagrams/{diagram['id']}", headers=auth_headers(member)).status_code == 200
    assert client.get(f"{base}/diagrams/{diagram['id']}/view", headers=auth_headers(member)).status_code == 200
    assert client.post(f"{base}/diagrams", json={"name": "No"}, headers=auth_headers(member)).status_code == 403
    assert client.put(
        f"{base}/diagrams/{diagram['id']}", json={"version": 1, "name": "No"}, headers=auth_headers(member),
    ).status_code == 403
    assert client.delete(f"{base}/diagrams/{diagram['id']}", headers=auth_headers(member)).status_code == 403
    architect = make_architect(client, token, org["id"], project["id"], "arch.diagram.architect@example.com")
    assert client.put(
        f"{base}/diagrams/{diagram['id']}", json={"version": 1, "name": "Renamed"}, headers=auth_headers(architect),
    ).status_code == 200
    assert client.get(f"{base}/diagrams/{diagram['id']}", headers=h).json()["name"] == "Renamed"


def test_an_edit_quotes_the_version_and_a_stale_one_is_refused(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch diagram version")
    diagram = make_diagram(client, token, project["id"], "Context")
    edited = _put(client, token, project["id"], diagram, "", {"purpose": "Why."})
    assert edited["version"] == 2 and edited["purpose"] == "Why."
    _put(client, token, project["id"], diagram, "", {"purpose": "Stale."}, expect=409)
    same = _put(client, token, project["id"], edited, "", {"purpose": "Why."})
    assert same["version"] == 2  # nothing changed, the version did not move


def test_status_archive_and_delete(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch diagram lifecycle")
    h = auth_headers(token)
    base = project_base(project["id"])
    diagram = make_diagram(client, token, project["id"], "Context")
    active = client.post(f"{base}/diagrams/{diagram['id']}/status", json={"version": 1, "status": "active"}, headers=h)
    assert active.status_code == 200 and active.json()["status"] == "active"
    assert client.post(f"{base}/diagrams/{diagram['id']}/status", json={"version": 2, "status": "active"}, headers=h).status_code == 409
    assert client.post(f"{base}/diagrams/{diagram['id']}/archive", headers=h).json()["is_archived"] is True
    assert client.get(f"{base}/diagrams", headers=h).json() == []
    assert len(client.get(f"{base}/diagrams", params={"include_archived": "true"}, headers=h).json()) == 1
    assert client.post(f"{base}/diagrams/{diagram['id']}/unarchive", headers=h).json()["is_archived"] is False
    assert client.delete(f"{base}/diagrams/{diagram['id']}", headers=h).status_code == 204
    assert client.get(f"{base}/diagrams/{diagram['id']}", headers=h).status_code == 404


def test_another_projects_diagram_and_the_scope_element_must_be_the_callers_to_read(client, admin_token):
    org, project, token = setup(client, admin_token, "Arch diagram tenants")
    other = create_project(client, token, org["id"], "Arch diagram tenants other")
    foreign = make_element(client, token, other["id"], "Foreign")
    mine = make_diagram(client, token, project["id"], "Mine")
    theirs = make_diagram(client, token, other["id"], "Theirs")
    base = project_base(project["id"])
    h = auth_headers(token)
    assert client.get(f"{base}/diagrams/{theirs['id']}", headers=h).status_code == 404
    assert client.delete(f"{base}/diagrams/{theirs['id']}", headers=h).status_code == 404
    # An architect of this project only cannot open the other project, so its element looks absent to them.
    architect = make_architect(client, token, org["id"], project["id"], "arch.diagram.tenants@example.com")
    make_diagram(client, architect, project["id"], "Bad scope", scope_element_id=foreign["id"], expect=400)
    place(client, architect, project["id"], mine, foreign["id"], expect=400)


# --- Layout and placements ----------------------------------------------------


def test_saving_a_layout_places_moves_and_unplaces_without_deleting_the_element(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch diagram layout")
    a = make_element(client, token, project["id"], "Gateway")
    b = make_element(client, token, project["id"], "Sensor")
    diagram = make_diagram(client, token, project["id"], "Context")
    saved = _put(client, token, project["id"], diagram, "/layout", {
        "placements": [{"element_id": a["id"], "x": 10, "y": 20}, {"element_id": b["id"], "x": 300, "y": 20, "width": 120}],
        "notes": [{"text": "Edge of the system", "x": 0, "y": -90}],
    })
    assert saved["version"] == 2 and saved["placement_count"] == 2 and saved["note_count"] == 1
    nodes = _layout(view(client, token, project["id"], diagram["id"]))
    assert (nodes[a["unique_code"]]["x"], nodes[b["unique_code"]]["width"]) == (10, 120)

    moved = _put(client, token, project["id"], saved, "/layout", {
        "placements": [{"element_id": a["id"], "x": 99, "y": 20}],
        "notes": [],
    })
    assert moved["placement_count"] == 1 and moved["note_count"] == 0
    still = client.get(f"{project_base(project['id'])}/elements/{b['id']}", headers=auth_headers(token))
    assert still.status_code == 200  # unplaced, never deleted


def test_a_layout_that_changes_nothing_does_not_advance_the_version(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch diagram noop")
    a = make_element(client, token, project["id"], "Gateway")
    diagram = make_diagram(client, token, project["id"], "Context")
    body = {"placements": [{"element_id": a["id"], "x": 5, "y": 5}], "notes": []}
    first = _put(client, token, project["id"], diagram, "/layout", body)
    again = _put(client, token, project["id"], first, "/layout", body)
    assert (first["version"], again["version"]) == (2, 2)


def test_a_layout_is_refused_when_stale_repeated_or_naming_an_unavailable_element(client, admin_token):
    org, project, token = setup(client, admin_token, "Arch diagram layout rules")
    other = create_project(client, token, org["id"], "Arch diagram layout rules other")
    a = make_element(client, token, project["id"], "Gateway")
    archived = make_element(client, token, project["id"], "Old")
    client.post(f"{project_base(project['id'])}/elements/{archived['id']}/archive", headers=auth_headers(token))
    foreign = make_element(client, token, other["id"], "Foreign")
    diagram = make_diagram(client, token, project["id"], "Context")
    architect = make_architect(client, token, org["id"], project["id"], "arch.diagram.layoutrules@example.com")
    placement = {"element_id": a["id"], "x": 0, "y": 0}
    _put(client, token, project["id"], {**diagram, "version": 9}, "/layout", {"placements": [placement]}, expect=409)
    _put(client, token, project["id"], diagram, "/layout", {"placements": [placement, placement]}, expect=400)
    _put(client, token, project["id"], diagram, "/layout", {"placements": [{"element_id": archived["id"]}]}, expect=400)
    # The architect belongs to this project only, so the other project's element looks absent to them.
    _put(client, architect, project["id"], diagram, "/layout", {"placements": [{"element_id": foreign["id"]}]}, expect=400)
    _put(client, token, project["id"], diagram, "/layout", {"placements": [{"element_id": str(uuid.uuid4())}]}, expect=400)
    _put(client, token, project["id"], diagram, "/layout", {"notes": [{"id": str(uuid.uuid4()), "text": "x"}]}, expect=400)
    # A box must be finite and bounded.
    _put(client, token, project["id"], diagram, "/layout", {"placements": [{"element_id": a["id"], "x": 1e12}]}, expect=422)
    _put(client, token, project["id"], diagram, "/layout", {"placements": [{"element_id": a["id"], "width": 0}]}, expect=422)


def test_one_element_is_placed_and_unplaced_with_the_version_lock(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch diagram single")
    a = make_element(client, token, project["id"], "Gateway")
    diagram = make_diagram(client, token, project["id"], "Context")
    placed = place(client, token, project["id"], diagram, a["id"], x=40, y=50)
    assert placed["version"] == 2 and placed["placement_count"] == 1
    place(client, token, project["id"], placed, a["id"], expect=400)  # already there
    place(client, token, project["id"], diagram, a["id"], expect=409)  # stale version
    base = project_base(project["id"])
    h = auth_headers(token)
    assert client.delete(f"{base}/diagrams/{diagram['id']}/placements/{a['id']}", params={"version": 1}, headers=h).status_code == 409
    removed = client.delete(f"{base}/diagrams/{diagram['id']}/placements/{a['id']}", params={"version": 2}, headers=h)
    assert removed.status_code == 200 and removed.json()["placement_count"] == 0
    assert client.delete(
        f"{base}/diagrams/{diagram['id']}/placements/{a['id']}", params={"version": 3}, headers=h,
    ).status_code == 404
    assert client.get(f"{base}/elements/{a['id']}", headers=h).status_code == 200


def test_deleting_an_element_removes_its_placement_and_deleting_a_diagram_keeps_the_model(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch diagram cascade")
    h = auth_headers(token)
    base = project_base(project["id"])
    a = make_element(client, token, project["id"], "Gateway")
    b = make_element(client, token, project["id"], "Sensor")
    link = make_connection(client, token, project["id"], a["id"], b["id"])
    diagram = place_all(client, token, project["id"], make_diagram(client, token, project["id"], "Context"), a["id"], b["id"])
    assert client.delete(f"{base}/connections/{link['id']}", headers=h).status_code == 204
    assert client.delete(f"{base}/elements/{b['id']}", headers=h).status_code == 204
    assert client.get(f"{base}/diagrams/{diagram['id']}", headers=h).json()["placement_count"] == 1
    assert client.delete(f"{base}/diagrams/{diagram['id']}", headers=h).status_code == 204
    assert client.get(f"{base}/elements/{a['id']}", headers=h).status_code == 200


# --- The resolved view ---------------------------------------------------------


def test_the_view_draws_a_connection_between_placed_elements_and_lists_its_ports(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch diagram view")
    a = make_element(client, token, project["id"], "Sensor node", ports=[{"name": "Out", "direction": "out"}])
    b = make_element(client, token, project["id"], "Gateway")
    link = make_connection(client, token, project["id"], a["id"], b["id"], name="Telemetry", protocol="MQTT 5")
    diagram = place_all(client, token, project["id"], make_diagram(client, token, project["id"], "Context"), a["id"], b["id"])
    shown = view(client, token, project["id"], diagram["id"])
    nodes = _layout(shown)
    assert [p["name"] for p in nodes[a["unique_code"]]["ports"]] == ["Out"]
    assert nodes[a["unique_code"]]["element_type_name"] == "Component" and nodes[a["unique_code"]]["locked"] is False
    (edge,) = shown["edges"]
    assert (edge["source_element_id"], edge["target_element_id"]) == (a["id"], b["id"])
    assert [c["id"] for c in edge["connections"]] == [link["id"]]
    assert (edge["indirect"], edge["bridged"], edge["rolled_up"], edge["count"]) == (False, False, False, 1)
    # A plain diagram shows no type, protocol or label on the line.
    assert edge["type_name"] is None and edge["label"] is None


def test_connection_detail_labels_the_line_and_plain_diagrams_merge_parallel_lines(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch diagram detail")
    a = make_element(client, token, project["id"], "Sensor node")
    b = make_element(client, token, project["id"], "Gateway")
    make_connection(client, token, project["id"], a["id"], b["id"], name="Data", protocol="MQTT 5")
    make_connection(client, token, project["id"], b["id"], a["id"], name="Control", protocol="MQTT 5", type_name="SPI")
    diagram = place_all(client, token, project["id"], make_diagram(client, token, project["id"], "Context"), a["id"], b["id"])
    plain = view(client, token, project["id"], diagram["id"])
    assert len(plain["edges"]) == 1 and plain["edges"][0]["count"] == 2 and plain["edges"][0]["label"] is None
    detailed = _put(client, token, project["id"], diagram, "", {"connection_detail": True})
    shown = view(client, token, project["id"], detailed["id"])
    assert len(shown["edges"]) == 2
    assert {e["type_name"] for e in shown["edges"]} == {"REST API", "SPI"}
    assert {e["label"] for e in shown["edges"]} == {"REST API · MQTT 5", "SPI · MQTT 5"}


def test_roll_up_draws_a_dashed_line_between_the_nearest_placed_ancestors(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch diagram rollup")
    platform = make_element(client, token, project["id"], "Platform", type_name="System")
    api = make_element(client, token, project["id"], "API", parent_id=platform["id"])
    db = make_element(client, token, project["id"], "Database", parent_id=platform["id"])
    cloud = make_element(client, token, project["id"], "Cloud", type_name="System")
    uplink = make_connection(client, token, project["id"], api["id"], cloud["id"], name="Uplink")
    make_connection(client, token, project["id"], db["id"], cloud["id"], name="Backup")
    internal = make_connection(client, token, project["id"], api["id"], db["id"], name="Query")
    diagram = place_all(client, token, project["id"], make_diagram(client, token, project["id"], "Context"), platform["id"], cloud["id"])
    shown = view(client, token, project["id"], diagram["id"])
    (edge,) = shown["edges"]
    assert (edge["source_element_id"], edge["target_element_id"]) == (platform["id"], cloud["id"])
    assert (edge["rolled_up"], edge["indirect"], edge["count"]) == (True, True, 2)
    assert uplink["id"] in {c["id"] for c in edge["connections"]}
    assert _layout(shown)[platform["unique_code"]]["internal_connection_ids"] == [internal["id"]]
    # Placing a child as well draws the real connection beside the rolled-up one.
    opened = place(client, token, project["id"], diagram, api["id"], x=0, y=200)
    again = view(client, token, project["id"], opened["id"])
    assert any(e["source_element_id"] == api["id"] and not e["rolled_up"] for e in again["edges"])


def test_a_retired_or_archived_connection_is_left_out_unless_asked_for(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch diagram retired")
    a = make_element(client, token, project["id"], "A")
    b = make_element(client, token, project["id"], "B")
    link = make_connection(client, token, project["id"], a["id"], b["id"])
    client.post(
        f"{project_base(project['id'])}/connections/{link['id']}/status", json={"version": 1, "status": "retired"},
        headers=auth_headers(token),
    )
    diagram = place_all(client, token, project["id"], make_diagram(client, token, project["id"], "Context"), a["id"], b["id"])
    assert view(client, token, project["id"], diagram["id"])["edges"] == []
    assert len(view(client, token, project["id"], diagram["id"], include_retired="true")["edges"]) == 1


# --- Toggles -------------------------------------------------------------------


def _firewall_diagram(client, token, project_id):
    """sensor -> firewall -> cloud, all placed, with a toggle holding the firewall by hand."""
    sensor = make_element(client, token, project_id, "Sensor", type_name="Sensor")
    firewall = make_element(client, token, project_id, "Firewall", type_name="Component")
    cloud = make_element(client, token, project_id, "Cloud", type_name="System")
    make_connection(client, token, project_id, sensor["id"], firewall["id"], name="In")
    make_connection(client, token, project_id, firewall["id"], cloud["id"], name="Out")
    diagram = place_all(client, token, project_id, make_diagram(client, token, project_id, "Flow"), sensor["id"], firewall["id"], cloud["id"])
    return sensor, firewall, cloud, diagram


def test_a_toggle_by_hand_bridges_the_hidden_element_and_lists_the_hop(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch diagram toggle manual")
    sensor, firewall, cloud, diagram = _firewall_diagram(client, token, project["id"])
    diagram = save_toggles(client, token, project["id"], diagram, [
        {"name": "Firewalls", "default_on": True, "element_ids": [firewall["id"]]},
    ])
    (toggle,) = view(client, token, project["id"], diagram["id"])["toggles"]
    assert (toggle["name"], toggle["on"], toggle["element_ids"]) == ("Firewalls", True, [firewall["id"]])
    on = view(client, token, project["id"], diagram["id"])
    assert len(on["edges"]) == 2 and not any(e["bridged"] for e in on["edges"])

    off = view(client, token, project["id"], diagram["id"], toggle_off=toggle["id"])
    (edge,) = off["edges"]
    assert (edge["source_element_id"], edge["target_element_id"]) == (sensor["id"], cloud["id"])
    assert (edge["bridged"], edge["indirect"]) == (True, True)
    assert [h["unique_code"] for h in edge["hops"]] == [firewall["unique_code"]]
    assert _layout(off)[firewall["unique_code"]]["hidden"] is True
    assert [t["on"] for t in off["toggles"]] == [False]


def test_a_saved_default_state_applies_unless_the_request_overrides_it(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch diagram toggle default")
    _s, firewall, _c, diagram = _firewall_diagram(client, token, project["id"])
    diagram = save_toggles(client, token, project["id"], diagram, [
        {"name": "Firewalls", "default_on": False, "element_ids": [firewall["id"]]},
    ])
    default = view(client, token, project["id"], diagram["id"])
    toggle_id = default["toggles"][0]["id"]
    assert default["toggles"][0]["on"] is False and len(default["edges"]) == 1
    forced_on = view(client, token, project["id"], diagram["id"], toggle_on=toggle_id)
    assert forced_on["toggles"][0]["on"] is True and len(forced_on["edges"]) == 2
    # The flipped state lives in the request: nothing was saved.
    assert view(client, token, project["id"], diagram["id"])["toggles"][0]["on"] is False


def test_a_toggle_rule_matches_by_element_type_domain_connection_type_and_tag(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch diagram toggle rule")
    h = auth_headers(token)
    sensor, firewall, cloud, diagram = _firewall_diagram(client, token, project["id"])
    types = element_types(client, token, project["id"])
    by_type = save_toggles(client, token, project["id"], diagram, [
        {"name": "Sensors", "default_on": False, "rule": {"element_type_ids": [types["Sensor"]]}},
    ])
    shown = view(client, token, project["id"], by_type["id"])
    assert _layout(shown)[sensor["unique_code"]]["hidden"] is True and shown["edges"][0]["source_element_id"] == firewall["id"]

    by_domain = save_toggles(client, token, project["id"], by_type, [
        {"name": "Hardware", "default_on": False, "rule": {"domains": ["hardware"]}},
    ])
    assert _layout(view(client, token, project["id"], by_domain["id"]))[sensor["unique_code"]]["hidden"] is True

    tagged = client.put(
        f"/api/v1/projects/{project['id']}/artefacts/architecture_element/{firewall['id']}/tags", json={"tags": ["security"]}, headers=h,
    )
    assert tagged.status_code in (200, 201), tagged.text
    by_tag = save_toggles(client, token, project["id"], by_domain, [
        {"name": "Security", "default_on": False, "rule": {"tags": ["security"]}},
    ])
    off = view(client, token, project["id"], by_tag["id"])
    assert _layout(off)[firewall["unique_code"]]["hidden"] is True and _layout(off)[sensor["unique_code"]]["hidden"] is False
    assert off["edges"][0]["bridged"] is True

    wire = connection_types(client, token, project["id"])["REST API"]
    by_connection = save_toggles(client, token, project["id"], by_tag, [
        {"name": "REST", "default_on": False, "rule": {"connection_type_ids": [wire]}},
    ])
    assert view(client, token, project["id"], by_connection["id"])["edges"] == []


def test_a_toggle_by_hand_can_hide_a_connection(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch diagram toggle connection")
    a = make_element(client, token, project["id"], "A")
    b = make_element(client, token, project["id"], "B")
    link = make_connection(client, token, project["id"], a["id"], b["id"])
    diagram = place_all(client, token, project["id"], make_diagram(client, token, project["id"], "Context"), a["id"], b["id"])
    diagram = save_toggles(client, token, project["id"], diagram, [
        {"name": "Debug link", "default_on": False, "connection_ids": [link["id"]]},
    ])
    assert view(client, token, project["id"], diagram["id"])["edges"] == []


def test_saving_toggles_checks_names_ids_types_and_members(client, admin_token):
    org, project, token = setup(client, admin_token, "Arch diagram toggle rules")
    other = create_project(client, token, org["id"], "Arch diagram toggle rules other")
    foreign_element = make_element(client, token, other["id"], "Foreign")
    mine = make_element(client, token, project["id"], "Mine")
    diagram = make_diagram(client, token, project["id"], "Context")
    architect = make_architect(client, token, org["id"], project["id"], "arch.diagram.togglerules@example.com")
    save_toggles(client, token, project["id"], diagram, [{"name": "A"}, {"name": "a"}], expect=400)
    save_toggles(client, token, project["id"], diagram, [{"name": "A", "id": str(uuid.uuid4())}], expect=400)
    save_toggles(client, architect, project["id"], diagram, [{"name": "A", "element_ids": [foreign_element["id"]]}], expect=400)
    save_toggles(client, token, project["id"], diagram, [{"name": "A", "connection_ids": [str(uuid.uuid4())]}], expect=400)
    save_toggles(client, token, project["id"], {**diagram, "version": 9}, [{"name": "A"}], expect=409)
    saved = save_toggles(client, token, project["id"], diagram, [{"name": "A", "element_ids": [mine["id"]]}])
    assert saved["toggle_count"] == 1


def test_toggles_can_be_renamed_swapped_and_removed(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch diagram toggle replace")
    diagram = make_diagram(client, token, project["id"], "Context")
    first = save_toggles(client, token, project["id"], diagram, [{"name": "One"}, {"name": "Two"}])
    ids = {t["name"]: t["id"] for t in view(client, token, project["id"], first["id"])["toggles"]}
    swapped = save_toggles(client, token, project["id"], first, [{"id": ids["One"], "name": "Two"}, {"id": ids["Two"], "name": "One"}])
    after = {t["name"]: t["id"] for t in view(client, token, project["id"], swapped["id"])["toggles"]}
    assert after == {"Two": ids["One"], "One": ids["Two"]}
    emptied = save_toggles(client, token, project["id"], swapped, [])
    assert emptied["toggle_count"] == 0


# --- Sharing -------------------------------------------------------------------


def test_a_shared_element_is_placed_and_connected_and_a_revoke_leaves_a_locked_placeholder(client, admin_token):
    org, owner, token = setup(client, admin_token, "Arch diagram shared")
    consumer = create_project(client, token, org["id"], "Arch diagram shared consumer")
    shared = make_element(client, token, owner["id"], "Platform secret name", activate=True)
    mine = make_element(client, token, consumer["id"], "Local app")
    base = project_base(owner["id"])
    collection = make_collection(client, token, base, "Infra", members=[shared["id"]])
    given = grant(client, token, base, collection["id"], project_id=consumer["id"])
    architect = make_architect(client, token, org["id"], consumer["id"], "arch.diagram.shared@example.com")
    make_connection(client, architect, consumer["id"], mine["id"], shared["id"])
    diagram = place_all(client, architect, consumer["id"], make_diagram(client, architect, consumer["id"], "Context"), mine["id"], shared["id"])
    shown = view(client, architect, consumer["id"], diagram["id"])
    node = _layout(shown)[shared["unique_code"]]
    assert (node["shared"], node["locked"], node["name"]) == (True, False, "Platform secret name")

    client.delete(f"{base}/collections/{collection['id']}/grants/{given['id']}", headers=auth_headers(token))
    revoked = view(client, architect, consumer["id"], diagram["id"])
    node = _layout(revoked)[shared["unique_code"]]
    assert node["locked"] is True and node["name"] == "" and node["ports"] == [] and node["element_type_name"] == ""
    assert "secret" not in str(revoked)
    # The diagram can still be saved with the locked element left in place.
    kept = _put(client, architect, consumer["id"], diagram, "/layout", {
        "placements": [{"element_id": mine["id"]}, {"element_id": shared["id"], "x": 400}],
    })
    assert kept["placement_count"] == 2


def test_a_shared_element_cannot_be_newly_placed_after_the_grant_is_gone_or_when_retired(client, admin_token):
    org, owner, token = setup(client, admin_token, "Arch diagram shared rules")
    consumer = create_project(client, token, org["id"], "Arch diagram shared rules consumer")
    shared = make_element(client, token, owner["id"], "Platform", activate=True)
    base = project_base(owner["id"])
    collection = make_collection(client, token, base, "Infra", members=[shared["id"]])
    given = grant(client, token, base, collection["id"], project_id=consumer["id"])
    architect = make_architect(client, token, org["id"], consumer["id"], "arch.diagram.sharedrules@example.com")
    diagram = make_diagram(client, architect, consumer["id"], "Context")
    client.post(
        f"{base}/elements/{shared['id']}/status", json={"version": shared["version"], "status": "retired"}, headers=auth_headers(token),
    )
    place(client, architect, consumer["id"], diagram, shared["id"], expect=400)  # retired shared element
    client.delete(f"{base}/collections/{collection['id']}/grants/{given['id']}", headers=auth_headers(token))
    place(client, architect, consumer["id"], diagram, shared["id"], expect=400)  # no access


# --- The SVG --------------------------------------------------------------------


def test_the_svg_draws_the_resolved_diagram_and_escapes_every_user_text(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch diagram svg")
    h = auth_headers(token)
    base = project_base(project["id"])
    a = make_element(client, token, project["id"], "Gate <script> & co", type_name="Service")
    b = make_element(client, token, project["id"], "Sensor", type_name="Sensor")
    make_connection(client, token, project["id"], a["id"], b["id"], protocol='"><svg onload=alert(1)>')
    diagram = place_all(client, token, project["id"], make_diagram(client, token, project["id"], "Flow", connection_detail=True), a["id"], b["id"])
    saved = _put(client, token, project["id"], diagram, "/layout", {
        "placements": [{"element_id": a["id"]}, {"element_id": b["id"], "x": 300}],
        "notes": [{"text": "</text><script>x</script>", "x": 0, "y": 150}],
    })
    resp = client.get(f"{base}/diagrams/{saved['id']}/svg", headers=h)
    assert resp.status_code == 200 and resp.headers["content-type"].startswith("image/svg+xml")
    assert "sandbox" in resp.headers["content-security-policy"] and resp.headers["cache-control"] == "private, no-store"
    svg = resp.text
    assert svg.startswith("<svg ") and "ELM-001" in svg and "Sensor" in svg
    assert "<script" not in svg
    assert "Gate &lt;script&gt; &amp; co" in svg
    # Well-formed XML with exactly the elements the renderer writes.
    import xml.etree.ElementTree as ET

    root = ET.fromstring(svg)
    tags = {el.tag.split("}")[-1] for el in root.iter()}
    assert "script" not in tags and "foreignObject" not in tags


def test_the_svg_leaves_out_what_a_toggle_hides_and_uses_the_requested_states(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch diagram svg toggle")
    h = auth_headers(token)
    _s, firewall, _c, diagram = _firewall_diagram(client, token, project["id"])
    diagram = save_toggles(client, token, project["id"], diagram, [{"name": "Firewalls", "element_ids": [firewall["id"]]}])
    toggle_id = view(client, token, project["id"], diagram["id"])["toggles"][0]["id"]
    base = project_base(project["id"])
    shown = client.get(f"{base}/diagrams/{diagram['id']}/svg", headers=h).text
    hidden = client.get(f"{base}/diagrams/{diagram['id']}/svg", params={"toggle_off": toggle_id}, headers=h).text
    assert firewall["unique_code"] in shown and firewall["unique_code"] not in hidden


def test_an_empty_diagram_still_renders_an_svg(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch diagram svg empty")
    diagram = make_diagram(client, token, project["id"], "Empty")
    resp = client.get(f"{project_base(project['id'])}/diagrams/{diagram['id']}/svg", headers=auth_headers(token))
    assert resp.status_code == 200 and "Empty diagram" in resp.text


def test_a_symbol_is_drawn_in_the_svg_and_the_view_names_it_only_when_readable(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch diagram svg symbol")
    a = make_element(client, token, project["id"], "Store", type_name="Datastore")  # seeded with the built-in database symbol
    diagram = place_all(client, token, project["id"], make_diagram(client, token, project["id"], "Context"), a["id"])
    shown = view(client, token, project["id"], diagram["id"])
    assert shown["nodes"][0]["symbol_id"] is not None
    resp = client.get(f"{project_base(project['id'])}/diagrams/{diagram['id']}/svg", headers=auth_headers(token))
    assert "<ellipse" in resp.text and 'style="color:' in resp.text


# --- Registration and audit -----------------------------------------------------


def test_the_summary_search_and_audit_trail_cover_diagrams(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch diagram registered")
    a = make_element(client, token, project["id"], "Gateway")
    diagram = make_diagram(client, token, project["id"], "Telemetry flow", purpose="How readings reach the cloud.")
    diagram = place_all(client, token, project["id"], diagram, a["id"])
    with SessionLocal() as db:
        found = get_artefact_summaries_in_project(
            db, uuid.UUID(project["id"]), "architecture_diagram", [uuid.UUID(diagram["id"])],
        )
    assert found is not None and {s.label for s in found.values()} == {"DGM-001 Telemetry flow"}
    resp = client.post(
        "/api/v1/search", json={"q": "readings", "scope": "project", "project_id": project["id"], "fields": ["id", "title", "description"]},
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    assert [h["title"] for h in resp.json()["hits"] if h["type"] == "architecture_diagram"] == ["Telemetry flow"]
    with SessionLocal() as db:
        events = list(db.scalars(
            select(AuditEvent).where(AuditEvent.entity_type == "architecture_diagram").order_by(AuditEvent.created_at)
        ))
    assert [e.action for e in events] == ["created", "layout_saved"]
    assert "Telemetry" not in " ".join(str(e.detail) for e in events) and "Gateway" not in " ".join(str(e.detail) for e in events)


def test_the_diagram_list_filters_and_exports(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch diagram list")
    h = auth_headers(token)
    base = project_base(project["id"])
    make_diagram(client, token, project["id"], "Context", activate=True)
    retired = make_diagram(client, token, project["id"], "Legacy")
    client.post(f"{base}/diagrams/{retired['id']}/status", json={"version": 1, "status": "retired"}, headers=h)
    assert [d["name"] for d in client.get(f"{base}/diagrams", params={"open_only": "true"}, headers=h).json()] == ["Context"]
    assert [d["name"] for d in client.get(f"{base}/diagrams", params={"status": "retired"}, headers=h).json()] == ["Legacy"]
    assert [d["name"] for d in client.get(f"{base}/diagrams", params={"search": "dgm-001"}, headers=h).json()] == ["Context"]
    exported = client.get(f"/api/v1/projects/{project['id']}/records/architecture_diagram/export", headers=h)
    assert exported.status_code == 200, exported.text
    header = exported.content.decode("utf-8-sig").splitlines()[0]
    assert header.startswith("code,name,purpose")
    refused = client.post(
        f"/api/v1/projects/{project['id']}/records/architecture_diagram/import", params={"dry_run": "true"},
        files={"file": ("records.csv", b"code,Name\n,x\n", "text/csv")}, headers=h,
    )
    assert refused.status_code in (400, 404, 405, 409, 422)
