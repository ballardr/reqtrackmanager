"""Tests for the diagram model endpoint (`GET .../diagrams/{id}/model`), the data the editor resolves lines from in the
browser: that the model holds everything the resolver needs and reproduces the server's own view for every switch state
and connection-detail setting, that it lists the elements a person could still place (so a newly placed box is hidden or
joined by the same rules), that what the viewer cannot read stays unreadable, that only members read it, and that its
statement count does not grow with the size of the project. Every test builds its own organisation."""

from __future__ import annotations

import itertools
import uuid

from sqlalchemy import event

from app.database import engine
from app.modules.architecture.diagram_resolver import ModelConnection, resolve
from app.modules.architecture.tests._helpers import (
    add_member,
    element_types,
    grant,
    make_architect,
    make_collection,
    make_connection,
    make_diagram,
    make_element,
    place_all,
    project_base,
    save_toggles,
    setup,
    view,
)
from tests.conftest import auth_headers, create_project


def model(client, token, project_id, diagram_id, *, expect=200) -> dict:
    """The diagram model of a diagram."""
    resp = client.get(f"{project_base(project_id)}/diagrams/{diagram_id}/model", headers=auth_headers(token))
    assert resp.status_code == expect, resp.text
    return resp.json()


def _tag(client, token, project_id, element_id, tag):
    resp = client.put(
        f"/api/v1/projects/{project_id}/artefacts/architecture_element/{element_id}/tags", json={"tags": [tag]},
        headers=auth_headers(token),
    )
    assert resp.status_code in (200, 201), resp.text


def _resolved_from(data: dict, placed: list[str], toggles_off: set[str], detail: bool):
    """What the browser does: combine the model's plain ids with the state and run the one resolver."""
    kinds = {t["id"]: t for t in data["connection_types"]}
    hidden_elements: set[uuid.UUID] = set()
    hidden_connections: set[uuid.UUID] = set()
    for members in data["toggle_members"]:
        if members["toggle_id"] in toggles_off:
            hidden_elements |= {uuid.UUID(i) for i in members["element_ids"]}
            hidden_connections |= {uuid.UUID(i) for i in members["connection_ids"]}
    return resolve(
        placed=[uuid.UUID(i) for i in placed],
        parents={uuid.UUID(k): (uuid.UUID(v) if v else None) for k, v in data["parents"].items()},
        connections=[
            ModelConnection(
                uuid.UUID(c["id"]), uuid.UUID(c["source_element_id"]), uuid.UUID(c["target_element_id"]),
                kinds[c["connection_type_id"]]["directional"],
            )
            for c in data["connections"]
        ],
        hidden_elements=hidden_elements, hidden_connections=hidden_connections, merge_parallel=not detail,
    )


def _line_shape(source, target, connection_ids, two_way, rolled_up, bridged, indirect, hops):
    """A line reduced to what must agree between the model and the view."""
    return (str(source), str(target), tuple(str(i) for i in connection_ids), two_way, rolled_up, bridged, indirect,
            tuple(str(h) for h in hops))


def test_the_model_reproduces_the_view_for_every_switch_state_and_detail_setting(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch model parity")
    pid = project["id"]
    platform = make_element(client, token, pid, "Platform", type_name="System")
    api = make_element(client, token, pid, "API", parent_id=platform["id"])
    db = make_element(client, token, pid, "Database", parent_id=platform["id"])
    cloud = make_element(client, token, pid, "Cloud", type_name="System")
    sensor = make_element(client, token, pid, "Sensor", type_name="Sensor")
    firewall = make_element(client, token, pid, "Firewall", type_name="Component")
    _tag(client, token, pid, firewall["id"], "security")
    make_connection(client, token, pid, sensor["id"], firewall["id"], name="In")
    make_connection(client, token, pid, firewall["id"], cloud["id"], name="Out")
    make_connection(client, token, pid, api["id"], cloud["id"], name="Uplink")
    make_connection(client, token, pid, db["id"], cloud["id"], name="Backup")
    make_connection(client, token, pid, api["id"], db["id"], name="Query")
    diagram = place_all(
        client, token, pid, make_diagram(client, token, pid, "Context"),
        platform["id"], cloud["id"], sensor["id"], firewall["id"],
    )
    diagram = save_toggles(client, token, pid, diagram, [
        {"name": "Security", "default_on": True, "rule": {"tags": ["security"]}},
        {"name": "Platform internals", "default_on": True, "element_ids": [api["id"]]},
    ])
    toggle_ids = [t["id"] for t in view(client, token, pid, diagram["id"])["toggles"]]

    seen = {"bridged": False, "rolled_up": False, "merged": False, "internal": False, "hidden": False}
    for detail, off in itertools.product((False, True), (set(), {toggle_ids[0]}, {toggle_ids[1]}, set(toggle_ids))):
        diagram = client.put(
            f"{project_base(pid)}/diagrams/{diagram['id']}", json={"version": diagram["version"], "connection_detail": detail},
            headers=auth_headers(token),
        ).json()
        shown = view(client, token, pid, diagram["id"], toggle_off=list(off))
        data = model(client, token, pid, diagram["id"])
        placed = [n["element_id"] for n in shown["nodes"]]
        resolution = _resolved_from(data, placed, off, detail)

        from_view = sorted(
            _line_shape(
                e["source_element_id"], e["target_element_id"], [c["id"] for c in e["connections"]], e["two_way"],
                e["rolled_up"], e["bridged"], e["indirect"], [h["element_id"] for h in e["hops"]],
            )
            for e in shown["edges"]
        )
        from_model = sorted(
            _line_shape(
                ln.source_id, ln.target_id, ln.connection_ids, ln.two_way, ln.rolled_up, ln.bridged, ln.indirect, ln.hops,
            )
            for ln in resolution.lines
        )
        assert from_model == from_view, (detail, off)
        seen["bridged"] |= any(e["bridged"] for e in shown["edges"])
        seen["rolled_up"] |= any(e["rolled_up"] for e in shown["edges"])
        seen["merged"] |= any(e["count"] > 1 for e in shown["edges"])
        seen["internal"] |= any(n["internal_connection_ids"] for n in shown["nodes"])
        seen["hidden"] |= any(n["hidden"] for n in shown["nodes"])
        assert {str(i) for i in resolution.hidden_placed} == {n["element_id"] for n in shown["nodes"] if n["hidden"]}
        assert {str(k): [str(i) for i in v] for k, v in resolution.internal.items()} == {
            n["element_id"]: n["internal_connection_ids"] for n in shown["nodes"] if n["internal_connection_ids"]
        }
    # The states above are only a real check if they reached every resolver behaviour.
    assert all(seen.values()), seen


def test_the_model_lists_elements_not_yet_placed_and_what_each_switch_hides(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch model candidates")
    pid = project["id"]
    types = element_types(client, token, pid)
    platform = make_element(client, token, pid, "Platform", type_name="System")
    child = make_element(client, token, pid, "Child", parent_id=platform["id"])
    spare = make_element(client, token, pid, "Spare sensor", type_name="Sensor")
    sensor = make_element(client, token, pid, "Sensor", type_name="Sensor")
    diagram = place_all(client, token, pid, make_diagram(client, token, pid, "Context"), platform["id"])
    diagram = save_toggles(client, token, pid, diagram, [
        {"name": "Sensors", "default_on": True, "rule": {"element_type_ids": [types["Sensor"]]}},
        {"name": "By hand", "default_on": False, "element_ids": [child["id"]]},
    ])
    data = model(client, token, pid, diagram["id"])

    ids = {e["id"]: e for e in data["elements"]}
    assert {spare["id"], sensor["id"], child["id"], platform["id"]} <= set(ids)
    assert ids[spare["id"]]["name"] == "Spare sensor" and ids[spare["id"]]["locked"] is False
    assert data["parents"][child["id"]] == platform["id"] and data["parents"][platform["id"]] is None
    by_name = {t["name"]: t["id"] for t in view(client, token, pid, diagram["id"])["toggles"]}
    members = {m["toggle_id"]: m for m in data["toggle_members"]}
    assert set(members[by_name["Sensors"]]["element_ids"]) == {spare["id"], sensor["id"]}
    assert members[by_name["By hand"]]["element_ids"] == [child["id"]]


def test_the_model_keeps_what_the_viewer_cannot_read_unreadable(client, admin_token):
    org, owner, token = setup(client, admin_token, "Arch model locked")
    consumer = create_project(client, token, org["id"], "Arch model locked consumer")
    shared = make_element(client, token, owner["id"], "Platform secret name", activate=True)
    mine = make_element(client, token, consumer["id"], "Local app")
    base = project_base(owner["id"])
    collection = make_collection(client, token, base, "Infra", members=[shared["id"]])
    given = grant(client, token, base, collection["id"], project_id=consumer["id"])
    architect = make_architect(client, token, org["id"], consumer["id"], "arch.model.locked@example.com")
    make_connection(client, architect, consumer["id"], mine["id"], shared["id"])
    diagram = place_all(client, architect, consumer["id"], make_diagram(client, architect, consumer["id"], "Context"),
                        mine["id"], shared["id"])

    readable = {e["id"]: e for e in model(client, architect, consumer["id"], diagram["id"])["elements"]}
    assert (readable[shared["id"]]["shared"], readable[shared["id"]]["locked"]) == (True, False)

    client.delete(f"{base}/collections/{collection['id']}/grants/{given['id']}", headers=auth_headers(token))
    revoked = model(client, architect, consumer["id"], diagram["id"])
    entry = next(e for e in revoked["elements"] if e["id"] == shared["id"])
    assert entry["locked"] is True and entry["name"] == "" and entry["element_type_name"] == "" and entry["symbol_id"] is None
    assert entry["unique_code"] == shared["unique_code"]
    assert "secret" not in str(revoked)


def test_any_member_reads_the_model_and_another_projects_diagram_is_absent(client, admin_token):
    org, project, token = setup(client, admin_token, "Arch model gate")
    other = create_project(client, token, org["id"], "Arch model gate other")
    mine = make_diagram(client, token, project["id"], "Mine")
    theirs = make_diagram(client, token, other["id"], "Theirs")
    _uid, member = add_member(client, token, org["id"], project["id"], "arch.model.member@example.com")
    assert model(client, member, project["id"], mine["id"]) is not None
    model(client, token, project["id"], theirs["id"], expect=404)
    model(client, token, project["id"], str(uuid.uuid4()), expect=404)
    assert client.get(f"{project_base(project['id'])}/diagrams/{mine['id']}/model").status_code in (401, 403)


class _Counter:
    """Counts SQL statements while active."""

    def __init__(self):
        self.count = 0

    def __call__(self, *_args, **_kwargs):
        self.count += 1

    def __enter__(self):
        event.listen(engine, "before_cursor_execute", self)
        return self

    def __exit__(self, *_exc):
        event.remove(engine, "before_cursor_execute", self)


def test_the_models_statement_count_does_not_grow_with_the_project(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch model flat")
    pid = project["id"]
    first = make_element(client, token, pid, "First")
    second = make_element(client, token, pid, "Second", parent_id=first["id"])
    make_connection(client, token, pid, first["id"], second["id"])
    diagram = place_all(client, token, pid, make_diagram(client, token, pid, "Context"), first["id"])
    model(client, token, pid, diagram["id"])
    with _Counter() as small:
        model(client, token, pid, diagram["id"])

    previous = second
    for index in range(8):
        element = make_element(client, token, pid, f"Extra {index}", parent_id=previous["id"] if index % 2 else None)
        make_connection(client, token, pid, previous["id"], element["id"], name=f"Link {index}")
        previous = element
    with _Counter() as large:
        data = model(client, token, pid, diagram["id"])
    assert len(data["connections"]) == 9
    assert large.count == small.count
