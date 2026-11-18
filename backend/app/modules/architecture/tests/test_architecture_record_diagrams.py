"""Tests for the Diagrams card reads (`GET /elements/{id}/diagrams`, `GET /connections/{id}/diagrams`): an element lists
the block diagrams that place it or an ancestor and the state machine diagrams that describe it; a connection lists the
diagrams that draw it, as its own line or one rolled up to ancestors; archived diagrams, a hidden element, a diagram
type whose sub-component is off and another project's records are absent; and the statements do not grow with the
number of diagrams. Every test builds its own organisation."""

from __future__ import annotations

from sqlalchemy import event

from app.database import engine
from app.modules.architecture.tests._helpers import (
    grant,
    make_architect,
    make_collection,
    make_connection,
    make_diagram,
    make_element,
    make_machine,
    place,
    project_base,
    setup,
)
from tests.conftest import auth_headers, create_project


def _diagrams(client, token, project_id, kind, record_id, expect=200):
    resp = client.get(f"{project_base(project_id)}/{kind}/{record_id}/diagrams", headers=auth_headers(token))
    assert resp.status_code == expect, resp.text
    return resp.json()


def _switch(client, token, project_id, key, enabled):
    resp = client.put(
        f"/api/v1/projects/{project_id}/modules/architecture/subcomponents/{key}", json={"enabled": enabled},
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text


def test_an_element_lists_the_block_diagrams_that_place_it_or_an_ancestor_and_its_state_machine_diagrams(client, admin_token):
    org, project, token = setup(client, admin_token, "Arch rec diagrams element")
    pid = project["id"]
    parent = make_element(client, token, pid, "Vehicle")
    child = make_element(client, token, pid, "Engine", parent_id=parent["id"])
    unrelated = make_element(client, token, pid, "Tool")
    direct = make_diagram(client, token, pid, "Direct")
    place(client, token, pid, direct, child["id"])
    via = make_diagram(client, token, pid, "Via parent")
    place(client, token, pid, via, parent["id"])
    other = make_diagram(client, token, pid, "Unrelated")
    place(client, token, pid, other, unrelated["id"])
    both = make_diagram(client, token, pid, "Both")
    both = place(client, token, pid, both, parent["id"])
    place(client, token, pid, both, child["id"])
    machine = make_machine(client, token, pid, child["id"], "Engine modes")

    rows = _diagrams(client, token, pid, "elements", child["id"])
    assert [(r["kind"], r["unique_code"], r["usage"]) for r in rows] == [
        ("block", direct["unique_code"], "placed"),
        ("block", via["unique_code"], "inside"),
        ("block", both["unique_code"], "placed"),
        ("state_machine", machine["unique_code"], "describes"),
    ]
    inside = rows[1]
    assert (inside["via_element_id"], inside["via_element_code"], inside["via_element_name"]) == (
        parent["id"], parent["unique_code"], "Vehicle",
    )
    assert _diagrams(client, token, pid, "elements", unrelated["id"])[0]["name"] == "Unrelated"
    assert _diagrams(client, token, pid, "elements", parent["id"])[0]["usage"] == "placed"


def test_an_archived_diagram_is_not_listed(client, admin_token):
    org, project, token = setup(client, admin_token, "Arch rec diagrams archived")
    pid = project["id"]
    element = make_element(client, token, pid, "Gear")
    diagram = make_diagram(client, token, pid, "Old")
    place(client, token, pid, diagram, element["id"])
    machine = make_machine(client, token, pid, element["id"], "Old modes")
    assert len(_diagrams(client, token, pid, "elements", element["id"])) == 2
    for path in (f"diagrams/{diagram['id']}", f"state-machine-diagrams/{machine['id']}"):
        assert client.post(f"{project_base(pid)}/{path}/archive", headers=auth_headers(token)).status_code == 200
    assert _diagrams(client, token, pid, "elements", element["id"]) == []


def test_a_connection_lists_the_diagrams_that_draw_it_including_a_rolled_up_line(client, admin_token):
    org, project, token = setup(client, admin_token, "Arch rec diagrams connection")
    pid = project["id"]
    left = make_element(client, token, pid, "Left")
    right = make_element(client, token, pid, "Right")
    left_part = make_element(client, token, pid, "Left part", parent_id=left["id"])
    connection = make_connection(client, token, pid, left_part["id"], right["id"])
    own = make_diagram(client, token, pid, "Own line")
    own = place(client, token, pid, own, left_part["id"])
    place(client, token, pid, own, right["id"])
    rolled = make_diagram(client, token, pid, "Rolled up")
    rolled = place(client, token, pid, rolled, left["id"])
    place(client, token, pid, rolled, right["id"])
    one_end = make_diagram(client, token, pid, "One end")
    place(client, token, pid, one_end, right["id"])
    inside = make_diagram(client, token, pid, "Inside one box")
    place(client, token, pid, inside, left["id"])

    rows = _diagrams(client, token, pid, "connections", connection["id"])
    assert [(r["unique_code"], r["usage"]) for r in rows] == [(own["unique_code"], "drawn"), (rolled["unique_code"], "rolled_up")]
    assert all(r["kind"] == "block" for r in rows)


def test_a_hidden_foreign_element_and_another_project_s_ids_answer_404(client, admin_token):
    org, owner, token = setup(client, admin_token, "Arch rec diagrams hidden")
    consumer = create_project(client, token, org["id"], "Arch rec diagrams hidden consumer")
    other = create_project(client, token, org["id"], "Arch rec diagrams hidden other")
    shared = make_element(client, token, owner["id"], "Platform")
    local = make_element(client, token, consumer["id"], "Local")
    peer = make_element(client, token, consumer["id"], "Peer")
    connection = make_connection(client, token, consumer["id"], local["id"], peer["id"])
    architect = make_architect(client, token, org["id"], consumer["id"], "arch.rec.diagrams.hidden@example.com")
    # Not shared with the consumer: the element is hidden and indistinguishable from an absent one.
    assert _diagrams(client, architect, consumer["id"], "elements", shared["id"], expect=404)
    # Shared: readable, and its diagrams of this project are listed.
    owner_base = project_base(owner["id"])
    collection = make_collection(client, token, owner_base, "Shared", members=[shared["id"]])
    grant(client, token, owner_base, collection["id"], project_id=consumer["id"])
    diagram = make_diagram(client, architect, consumer["id"], "Uses platform")
    place(client, architect, consumer["id"], diagram, shared["id"])
    assert [r["name"] for r in _diagrams(client, architect, consumer["id"], "elements", shared["id"])] == ["Uses platform"]
    # Another project's records are absent.
    outsider = make_architect(client, token, org["id"], other["id"], "arch.rec.diagrams.outsider@example.com")
    assert _diagrams(client, outsider, other["id"], "elements", local["id"], expect=404)
    assert _diagrams(client, outsider, other["id"], "connections", connection["id"], expect=404)


def test_a_diagram_type_whose_sub_component_is_off_is_absent(client, admin_token):
    org, project, token = setup(client, admin_token, "Arch rec diagrams gates")
    pid = project["id"]
    element = make_element(client, token, pid, "Gear")
    peer = make_element(client, token, pid, "Peer")
    connection = make_connection(client, token, pid, element["id"], peer["id"])
    diagram = make_diagram(client, token, pid, "Drawn")
    diagram = place(client, token, pid, diagram, element["id"])
    place(client, token, pid, diagram, peer["id"])
    make_machine(client, token, pid, element["id"], "Modes")
    assert [r["kind"] for r in _diagrams(client, token, pid, "elements", element["id"])] == ["block", "state_machine"]

    _switch(client, token, pid, "architecture_state_machine", False)
    assert [r["kind"] for r in _diagrams(client, token, pid, "elements", element["id"])] == ["block"]
    _switch(client, token, pid, "architecture_state_machine", True)
    _switch(client, token, pid, "architecture_diagram", False)
    assert [r["kind"] for r in _diagrams(client, token, pid, "elements", element["id"])] == ["state_machine"]
    assert _diagrams(client, token, pid, "connections", connection["id"]) == []


def test_the_reads_use_the_same_number_of_statements_however_many_diagrams(client, admin_token):
    org, project, token = setup(client, admin_token, "Arch rec diagrams flat")
    pid = project["id"]
    parent = make_element(client, token, pid, "Vehicle")
    child = make_element(client, token, pid, "Engine", parent_id=parent["id"])
    peer = make_element(client, token, pid, "Peer")
    connection = make_connection(client, token, pid, child["id"], peer["id"])
    architect = make_architect(client, token, org["id"], pid, "arch.rec.diagrams.flat@example.com")
    urls = [f"{project_base(pid)}/elements/{child['id']}/diagrams", f"{project_base(pid)}/connections/{connection['id']}/diagrams"]

    def count(url) -> int:
        seen: list[str] = []

        def record(_conn, _cursor, statement, *_args):
            seen.append(statement)

        event.listen(engine, "before_cursor_execute", record)
        try:
            assert client.get(url, headers=auth_headers(architect)).status_code == 200
        finally:
            event.remove(engine, "before_cursor_execute", record)
        return len(seen)

    def add(n: int) -> None:
        for i in range(n):
            diagram = make_diagram(client, token, pid, f"Flat {n} {i}")
            diagram = place(client, token, pid, diagram, parent["id"] if i % 2 else child["id"])
            place(client, token, pid, diagram, peer["id"])
        make_machine(client, token, pid, child["id"], f"Flat modes {n}")

    add(2)
    few = [count(u) for u in urls]
    add(6)
    assert [count(u) for u in urls] == few
    assert len(_diagrams(client, token, pid, "elements", child["id"])) == 10
    assert len(_diagrams(client, token, pid, "connections", connection["id"])) == 8
