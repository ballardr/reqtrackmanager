"""Tests for the Mermaid export of a diagram: it writes the same resolved nodes and lines as the view (toggles, bridging,
roll-up, merging), leaves out what a toggle hides, escapes every user text so a name cannot end its label or add markup,
keeps to the lines Mermaid reads, and is read by the same gate as the view. Every test builds its own organisation."""

from __future__ import annotations

import re

from app.modules.architecture.tests._helpers import (
    add_member,
    make_connection,
    make_diagram,
    make_element,
    place_all,
    project_base,
    save_toggles,
    setup,
    view,
)
from tests.conftest import auth_headers

#: The only three line shapes the export writes after its header: a comment, a node, a line between two nodes.
_NODE = re.compile(r'^    n\d+(\[|\(|\[\(|\{\{|\(\[|\[/|\[\[)"[^"]*"(\]|\)|\)\]|\}\}|\]\)|/\]|\]\])$')
_LINE = re.compile(r'^    n\d+ (-->|-\.->|<-->|<-\.->)(\|"[^"]*"\|)? n\d+$')


def _mermaid(client, token, project_id, diagram_id, *, expect=200, **params) -> str:
    resp = client.get(f"{project_base(project_id)}/diagrams/{diagram_id}/mermaid", params=params, headers=auth_headers(token))
    assert resp.status_code == expect, resp.text
    return resp.text


def _body(text: str) -> list[str]:
    lines = text.splitlines()
    assert lines[0].startswith("%% ") and lines[1] == "flowchart LR" and text.endswith("\n")
    return lines[2:]


def _firewall_diagram(client, token, project_id):
    sensor = make_element(client, token, project_id, "Sensor", type_name="Sensor")
    firewall = make_element(client, token, project_id, "Firewall", type_name="Component")
    cloud = make_element(client, token, project_id, "Cloud", type_name="System")
    make_connection(client, token, project_id, sensor["id"], firewall["id"], name="In")
    make_connection(client, token, project_id, firewall["id"], cloud["id"], name="Out")
    diagram = place_all(client, token, project_id, make_diagram(client, token, project_id, "Flow"), sensor["id"], firewall["id"], cloud["id"])
    return sensor, firewall, cloud, diagram


def test_the_text_has_one_node_per_placed_element_and_one_line_per_resolved_line(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch mermaid basic")
    _sensor, _firewall, _cloud, diagram = _firewall_diagram(client, token, project["id"])
    resp = client.get(f"{project_base(project['id'])}/diagrams/{diagram['id']}/mermaid", headers=auth_headers(token))
    assert resp.status_code == 200 and resp.headers["content-type"].startswith("text/plain")
    assert resp.headers["x-content-type-options"] == "nosniff" and resp.headers["cache-control"] == "private, no-store"
    body = _body(resp.text)
    nodes, lines = [x for x in body if not _LINE.match(x)], [x for x in body if _LINE.match(x)]
    assert all(_NODE.match(n) for n in nodes) and len(nodes) == 3
    assert len(lines) == len(view(client, token, project["id"], diagram["id"])["edges"]) == 2
    assert 'n1[("ELM-001<br/>Sensor")]' not in resp.text  # a Sensor is not a cylinder
    assert "ELM-001<br/>Sensor" in resp.text and "ELM-003<br/>Cloud" in resp.text


def test_an_arrow_follows_each_lines_direction_and_dotted_marks_an_indirect_line(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch mermaid arrows")
    a = make_element(client, token, project["id"], "A")
    b = make_element(client, token, project["id"], "B")
    c = make_element(client, token, project["id"], "C")
    make_connection(client, token, project["id"], a["id"], b["id"], type_name="REST API")
    make_connection(client, token, project["id"], b["id"], c["id"], type_name="Ethernet")
    diagram = place_all(client, token, project["id"], make_diagram(client, token, project["id"], "Arrows"), a["id"], b["id"], c["id"])
    edges = view(client, token, project["id"], diagram["id"])["edges"]
    assert {e["two_way"] for e in edges} == {True, False}  # the seeded types cover both
    lines = [x for x in _body(_mermaid(client, token, project["id"], diagram["id"])) if _LINE.match(x)]
    arrows = sorted(m.group(1) for m in (_LINE.match(x) for x in lines) if m is not None)
    assert arrows == sorted(("<-->" if e["two_way"] else "-->") for e in edges)


def test_a_toggle_off_leaves_the_hidden_element_out_and_draws_the_bridged_line_dotted(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch mermaid toggle")
    _sensor, firewall, _cloud, diagram = _firewall_diagram(client, token, project["id"])
    diagram = save_toggles(client, token, project["id"], diagram, [{"name": "Firewalls", "element_ids": [firewall["id"]]}])
    toggle_id = view(client, token, project["id"], diagram["id"])["toggles"][0]["id"]
    shown = _mermaid(client, token, project["id"], diagram["id"])
    hidden = _mermaid(client, token, project["id"], diagram["id"], toggle_off=toggle_id)
    assert "Firewall" in shown and "Firewall" not in hidden and firewall["unique_code"] not in hidden
    body = _body(hidden)
    assert len([x for x in body if _LINE.match(x)]) == 1 and "-.->" in hidden  # one bridged, indirect line
    assert all(_NODE.match(x) or _LINE.match(x) for x in body)


def test_a_line_that_stands_for_several_connections_carries_its_count(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch mermaid count")
    a = make_element(client, token, project["id"], "A")
    b = make_element(client, token, project["id"], "B")
    for _ in range(3):
        make_connection(client, token, project["id"], a["id"], b["id"])
    diagram = place_all(client, token, project["id"], make_diagram(client, token, project["id"], "Merged"), a["id"], b["id"])
    assert '|"×3"|' in _mermaid(client, token, project["id"], diagram["id"])


def test_connection_detail_labels_a_line_with_its_type_and_protocol(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch mermaid detail")
    a = make_element(client, token, project["id"], "A")
    b = make_element(client, token, project["id"], "B")
    make_connection(client, token, project["id"], a["id"], b["id"], protocol="HTTPS")
    diagram = place_all(
        client, token, project["id"], make_diagram(client, token, project["id"], "Detail", connection_detail=True), a["id"], b["id"],
    )
    assert '|"REST API · HTTPS"|' in _mermaid(client, token, project["id"], diagram["id"])


def test_every_user_text_is_escaped_so_it_cannot_end_a_label_or_add_markup(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch mermaid escape")
    hostile = 'Gate "x" <img src=x onerror=alert(1)> #1 & `code`'
    a = make_element(client, token, project["id"], hostile)
    b = make_element(client, token, project["id"], "Sink")
    make_connection(client, token, project["id"], a["id"], b["id"], protocol='"|n9 --> n1["')
    diagram = place_all(
        client, token, project["id"], make_diagram(client, token, project["id"], 'Flow "quoted"\n%%{init: {}}%%', connection_detail=True),
        a["id"], b["id"],
    )
    text = _mermaid(client, token, project["id"], diagram["id"])
    body = _body(text)
    assert all(_NODE.match(x) or _LINE.match(x) for x in body), body
    assert len(text.splitlines()) == 2 + len(body) and text.splitlines()[0].count("\n") == 0
    assert "<img" not in text and "onerror=alert(1)>" not in text and "`" not in text
    assert "Gate #quot;x#quot; #lt;img" in text and "#35;1 #amp; #96;code#96;" in text
    assert not any(x.startswith("%%{") for x in text.splitlines())  # a title cannot become a directive


def test_an_empty_diagram_writes_a_placeholder_node(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch mermaid empty")
    diagram = make_diagram(client, token, project["id"], "Empty")
    body = _body(_mermaid(client, token, project["id"], diagram["id"]))
    assert body == ['    empty["Empty diagram"]']


def test_a_person_who_cannot_open_the_project_cannot_read_the_text(client, admin_token):
    org, project, token = setup(client, admin_token, "Arch mermaid access")
    diagram = make_diagram(client, token, project["id"], "Private")
    _other_id, other_token = add_member(client, token, org["id"], project["id"], "mermaid.reader@example.com")
    assert _mermaid(client, other_token, project["id"], diagram["id"]).startswith("%% ")  # a member may read it
    from tests.conftest import create_project

    elsewhere = create_project(client, token, org["id"], "Elsewhere")
    _mermaid(client, other_token, elsewhere["id"], diagram["id"], expect=404)  # no access: indistinguishable from absent
    _mermaid(client, token, elsewhere["id"], diagram["id"], expect=404)  # another project's diagram looks absent
