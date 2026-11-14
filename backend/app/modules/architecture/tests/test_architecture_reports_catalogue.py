"""Tests for the reports AR2 to AR7: allocation coverage, interface list, element breakdown, diagram, unconnected
elements and state machines, with the drawing a report section can carry. Every test builds its own organisation."""

from __future__ import annotations

from datetime import UTC, datetime

from app.modules.architecture.tests._helpers import (
    make_connection,
    make_diagram,
    make_element,
    place_all,
    project_base,
    setup,
    sound_machine,
)
from app.services.report_framework import ReportResult, ReportSection, build_result_document
from app.services.report_model import Image
from app.services.report_widget_run import output_digest, part_blocks
from app.services.report_widgets import WidgetPart
from tests.conftest import auth_headers
from tests.link_world import World

ELEMENT = "architecture_element"


def _report(client, token, project_id, slug, **params):
    resp = client.get(f"{project_base(project_id)}/reports/{slug}", params={"format": "json", **params}, headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return resp.json()


def _rows(report) -> dict[str, list[list[str]]]:
    return {s["key"]: s["rows"] for s in report["sections"]}


# --- AR2 allocation coverage ------------------------------------------------------


def test_allocation_coverage_lists_the_gaps_and_agrees_with_the_overview_figures(client, admin_token):
    world = World(client, admin_token, "Report alloc")
    world.enable("architecture")
    project = world.project("Alloc report")
    requirement = world.requirement(project, "Needs an element")
    placed = make_element(client, world.token, project["id"], "Placed")
    make_element(client, world.token, project["id"], "Loose")
    resp = client.put(
        f"/api/v1/projects/{project['id']}/artefacts/{ELEMENT}/{placed['id']}/placements",
        json={"placements": [{"component_id": project["component_id"], "category_id": None}]}, headers=auth_headers(world.token),
    )
    assert resp.status_code == 200, resp.text

    report = _report(client, world.token, project["id"], "allocation-coverage")
    rows = _rows(report)
    assert [r[1] for r in rows["requirements"]] == ["Needs an element"]
    assert rows["requirements"][0][3].startswith(placed["unique_code"])
    assert sorted(r[1] for r in rows["elements"]) == ["Loose", "Placed"]
    assert report["data"]["unallocated_requirements"] == 1 and report["data"]["suggestions"] == 1
    assert report["data"]["unallocated_elements"] == 2

    accept = client.post(
        f"{project_base(project['id'])}/allocation/accept", headers=auth_headers(world.token),
        json={"pairs": [{"requirement_id": str(requirement), "element_id": placed["id"]}]},
    )
    assert accept.status_code == 200, accept.text
    after = _report(client, world.token, project["id"], "allocation-coverage")
    assert after["data"]["unallocated_requirements"] == 0 and after["data"]["suggestions"] == 0
    assert [r[1] for r in _rows(after)["elements"]] == ["Loose"]


def test_a_leaf_element_with_no_owner_and_a_connection_with_no_requirement_are_listed(client, admin_token):
    _org, project, token = setup(client, admin_token, "Report unowned")
    parent = make_element(client, token, project["id"], "Parent")
    child = make_element(client, token, project["id"], "Child", parent_id=parent["id"])
    other = make_element(client, token, project["id"], "Other")
    connection = make_connection(client, token, project["id"], child["id"], other["id"])
    rows = _rows(_report(client, token, project["id"], "allocation-coverage"))
    assert {r[1] for r in rows["unowned"]} == {"Child", "Other"}
    assert [r[0] for r in rows["connections"]] == [connection["unique_code"]]


# --- AR3 interface list -------------------------------------------------------------


def test_the_interface_list_names_both_ends_the_type_and_the_protocol_and_filters(client, admin_token):
    _org, project, token = setup(client, admin_token, "Report interfaces")
    a = make_element(client, token, project["id"], "Encoder")
    b = make_element(client, token, project["id"], "Cloud")
    c = make_element(client, token, project["id"], "Display")
    first = make_connection(client, token, project["id"], a["id"], b["id"], protocol="v2")
    make_connection(client, token, project["id"], b["id"], c["id"], type_name="gRPC")
    report = _report(client, token, project["id"], "interface-list")
    by_code = {r[0]: r for r in _rows(report)["connections"]}
    row = by_code[first["unique_code"]]
    assert row[2] == "REST API" and row[3] == "v2" and row[4].startswith(a["unique_code"]) and row[5].startswith(b["unique_code"])
    assert report["data"] == {"connections": 2, "with_requirement": 0}
    only_grpc = _rows(_report(client, token, project["id"], "interface-list", type="grpc"))["connections"]
    assert [r[2] for r in only_grpc] == ["gRPC"]
    touching = _rows(_report(client, token, project["id"], "interface-list", element=a["unique_code"]))["connections"]
    assert [r[0] for r in touching] == [first["unique_code"]]


# --- AR4 element breakdown ---------------------------------------------------------------


def test_the_breakdown_lists_each_element_under_its_parent_with_its_level(client, admin_token):
    _org, project, token = setup(client, admin_token, "Report tree")
    root = make_element(client, token, project["id"], "System")
    mid = make_element(client, token, project["id"], "Board", parent_id=root["id"])
    make_element(client, token, project["id"], "Chip", parent_id=mid["id"])
    make_element(client, token, project["id"], "Lone")
    rows = _rows(_report(client, token, project["id"], "element-breakdown"))["tree"]
    assert [(r[0], r[1].split(" ", 1)[1]) for r in rows] == [("1", "System"), ("2", "Board"), ("3", "Chip"), ("1", "Lone")]
    assert rows[1][5] == root["unique_code"] and rows[0][6] == "1"
    below = _rows(_report(client, token, project["id"], "element-breakdown", element="board"))["tree"]
    assert [r[1].split(" ", 1)[1] for r in below] == ["Board", "Chip"]


# --- AR5 diagram ---------------------------------------------------------------------------


def test_the_diagram_report_draws_what_the_svg_endpoint_draws(client, admin_token):
    _org, project, token = setup(client, admin_token, "Report drawing")
    a = make_element(client, token, project["id"], "Encoder")
    b = make_element(client, token, project["id"], "Cloud")
    make_connection(client, token, project["id"], a["id"], b["id"])
    diagram = make_diagram(client, token, project["id"], "Context")
    place_all(client, token, project["id"], diagram, a["id"], b["id"])

    report = _report(client, token, project["id"], "diagram", diagram=diagram["unique_code"])
    assert report["data"] == {"nodes": 2, "lines": 1, "drawn": True}
    assert len(_rows(report)["elements"]) == 2 and _rows(report)["lines"][0][2] == "REST API"
    # The drawing section is not shown on screen (it carries no table); the PDF carries the picture.
    pdf = client.get(
        f"{project_base(project['id'])}/reports/diagram", params={"format": "pdf", "diagram": "Context"}, headers=auth_headers(token),
    )
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")

    nothing = _report(client, token, project["id"], "diagram")
    assert nothing["data"]["drawn"] is False and any("diagram parameter" in n for n in nothing["notes"])
    missing = _report(client, token, project["id"], "diagram", diagram="Nope")
    assert missing["data"]["drawn"] is False and any("Nope" in n for n in missing["notes"])


# --- AR6 unconnected elements --------------------------------------------------------------


def test_an_element_is_unconnected_unless_it_or_something_below_it_is_connected(client, admin_token):
    _org, project, token = setup(client, admin_token, "Report unconnected")
    parent = make_element(client, token, project["id"], "Parent")
    child = make_element(client, token, project["id"], "Child", parent_id=parent["id"])
    other = make_element(client, token, project["id"], "Other")
    lonely = make_element(client, token, project["id"], "Lonely")
    make_connection(client, token, project["id"], child["id"], other["id"])
    diagram = make_diagram(client, token, project["id"], "Context")
    place_all(client, token, project["id"], diagram, other["id"])
    report = _report(client, token, project["id"], "unconnected-elements")
    rows = _rows(report)
    assert [r[1] for r in rows["unconnected"]] == ["Lonely"]
    assert {r[1] for r in rows["undrawn"]} == {"Parent", "Child", "Lonely"}
    assert report["data"] == {"unconnected": 1, "not_on_a_diagram": 3} and lonely["unique_code"]


# --- AR7 state machines -----------------------------------------------------------------------


def test_the_state_machine_report_lists_states_and_transitions_and_draws_one_diagram(client, admin_token):
    _org, project, token = setup(client, admin_token, "Report machines")
    element = make_element(client, token, project["id"], "Pump")
    machine, _states = sound_machine(client, token, project["id"], element["id"])
    report = _report(client, token, project["id"], "state-machines", state_machine=machine["unique_code"])
    rows = _rows(report)
    assert len(rows["machines"]) == 1 and rows["machines"][0][3:5] == ["3", "2"]
    assert [r[1].split(" ", 1)[1] for r in rows["states"]] == ["Start", "Running", "Stop"]
    assert [r[3] for r in rows["transitions"]] == ["", "halt"]
    assert report["data"] == {"diagrams": 1, "states": 3, "transitions": 2, "drawn": True}
    assert _report(client, token, project["id"], "state-machines")["data"]["drawn"] is False
    other = make_element(client, token, project["id"], "Valve")
    assert _rows(_report(client, token, project["id"], "state-machines", element=other["name"]))["machines"] == []


# --- A section that carries a drawing ----------------------------------------------------------


def _drawing_result() -> ReportResult:
    return ReportResult(
        key="x", title="X", scope_label="P", generated_at=datetime.now(UTC), notes=[],
        sections=[ReportSection("drawing", "Drawing", [], [], screen=False, drawing='<svg xmlns="http://www.w3.org/2000/svg"/>')],
    )


def test_a_drawing_section_prints_as_a_picture_in_the_document_and_in_a_widget():
    result = _drawing_result()
    assert any(isinstance(b, Image) and b.svg for b in build_result_document(result).blocks)
    blocks = part_blocks(result, WidgetPart("drawing", "Drawing", "", "section"))
    assert len(blocks) == 1 and isinstance(blocks[0], Image) and blocks[0].width == 100
    warnings: list[str] = []
    part_blocks(result, WidgetPart("drawing", "Drawing", "", "section"), [{"column": "A"}], warnings.append)
    assert warnings
    changed = _drawing_result()
    changed.sections[0].drawing = '<svg xmlns="http://www.w3.org/2000/svg"><g/></svg>'
    assert output_digest(result) != output_digest(changed)


def test_the_starter_parts_name_widgets_that_exist():
    from app.modules.registry import get_report_starter_sections
    from app.services.report_starter_blocks import ENGINEERING_SPECIFICATION, REVIEW_PACKAGE
    from app.services.report_widgets import find_widget

    for starter in (ENGINEERING_SPECIFICATION, REVIEW_PACKAGE):
        parts = [section for module_key, section in get_report_starter_sections(starter) if module_key == "architecture"]
        assert len(parts) == 1
        keys = [node["key"] for node in parts[0].nodes if node.get("type") == "widget"]
        assert keys and all(find_widget(key) is not None for key in keys)
