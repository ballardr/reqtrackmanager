"""Tests for the element and connection record tables: the list exports as the CSV it imports, a row with a code
updates the record through the rules the endpoints apply, a blank code creates one, references are by name or code
within the project, the export follows the list's filters and a plain member cannot import. Every test builds its
own organisation."""

from __future__ import annotations

import csv
import io

from app.modules.architecture.tests._helpers import (
    add_member,
    make_connection,
    make_element,
    project_base,
    setup,
)
from tests.conftest import auth_headers

ELEMENT = "architecture_element"
CONNECTION = "architecture_connection"


def _tier(project: dict, record_type: str) -> str:
    return f"/api/v1/projects/{project['id']}/records/{record_type}"


def _rows(resp) -> list[dict]:
    assert resp.status_code == 200, resp.text
    return list(csv.DictReader(io.StringIO(resp.content.decode("utf-8-sig"))))


def _csv(header: list[str], *rows: list[str]) -> str:
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(header)
    writer.writerows(rows)
    return out.getvalue()


def _import(client, token, tier, text: str, *, apply: bool = True):
    resp = client.post(
        f"{tier}/import", params={"dry_run": "false" if apply else "true"},
        files={"file": ("records.csv", text.encode("utf-8"), "text/csv")}, headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _element_list(client, token, project_id) -> dict[str, dict]:
    resp = client.get(f"{project_base(project_id)}/elements", params={"include_archived": "true"}, headers=auth_headers(token))
    return {e["name"]: e for e in resp.json()}


def test_elements_export_with_codes_parents_ports_and_follow_the_filters(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch tables export")
    board = make_element(
        client, token, project["id"], "Main board", type_name="Board", activate=True,
        ports=[{"name": "Main", "direction": "in"}, {"name": "Debug"}],
    )
    make_element(client, token, project["id"], "Temp sensor", type_name="Sensor", parent_id=board["id"])
    rows = _rows(client.get(f"{_tier(project, ELEMENT)}/export", headers=auth_headers(token)))
    by_name = {r["name"]: r for r in rows}
    assert by_name["Main board"]["code"] == "ELM-001" and by_name["Main board"]["type"] == "Board"
    assert by_name["Main board"]["status"] == "Active" and by_name["Main board"]["ports"] == "Main:In;Debug:Both"
    assert by_name["Temp sensor"]["parent"] == "ELM-001" and by_name["Temp sensor"]["status"] == "Draft"
    active = _rows(client.get(f"{_tier(project, ELEMENT)}/export", params={"status": "active"}, headers=auth_headers(token)))
    assert [r["name"] for r in active] == ["Main board"]
    typed = _rows(client.get(f"{_tier(project, ELEMENT)}/export", params={"type": "Sensor"}, headers=auth_headers(token)))
    assert [r["name"] for r in typed] == ["Temp sensor"]


def test_a_row_with_a_code_updates_the_element_and_an_unchanged_export_changes_nothing(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch tables update")
    element = make_element(client, token, project["id"], "Gateway", ports=[{"name": "Main"}])
    exported = client.get(f"{_tier(project, ELEMENT)}/export", headers=auth_headers(token)).content.decode("utf-8-sig")
    result = _import(client, token, _tier(project, ELEMENT), exported)
    assert (result["created"], result["updated"], result["unchanged"], result["failed"]) == (0, 0, 1, 0)

    text = _csv(["code", "description", "status", "ports"], [element["unique_code"], "Reworded.", "Active", "Main:Both;Extra:Out"])
    result = _import(client, token, _tier(project, ELEMENT), text)
    assert result["updated"] == 1 and result["failed"] == 0, result
    current = _element_list(client, token, project["id"])["Gateway"]
    assert current["description"] == "Reworded." and current["status"] == "active"
    assert [p["name"] for p in current["ports"]] == ["Main", "Extra"] and current["version"] > element["version"]


def test_a_blank_code_creates_an_element_under_a_parent_and_refuses_a_retired_start(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch tables create")
    parent = make_element(client, token, project["id"], "System root", type_name="System")
    text = _csv(
        ["code", "name", "type", "parent", "status", "ports"],
        ["", "Imported child", "Component", parent["unique_code"], "Active", "Bus:Out"],
        ["", "Retired start", "Component", "", "Retired", ""],
        ["", "Bad parent", "Component", "ELM-099", "", ""],
        ["", "Bad type", "Nonsense", "", "", ""],
    )
    result = _import(client, token, _tier(project, ELEMENT), text)
    assert (result["created"], result["failed"]) == (1, 3), result
    child = _element_list(client, token, project["id"])["Imported child"]
    assert child["parent_id"] == parent["id"] and child["status"] == "active" and child["unique_code"] == "ELM-002"
    assert child["ports"][0]["name"] == "Bus" and child["ports"][0]["direction"] == "out"
    assert "Retired start" not in _element_list(client, token, project["id"])


def test_an_unknown_code_or_another_projects_code_is_a_row_error(client, admin_token):
    org, project, token = setup(client, admin_token, "Arch tables unknown")
    from tests.conftest import create_project

    other = create_project(client, token, org["id"], "Arch tables unknown other")
    foreign = make_element(client, token, other["id"], "Foreign")
    text = _csv(["code", "description"], ["ELM-099", "Ghost"], [foreign["unique_code"], "Reach across"])
    result = _import(client, token, _tier(project, ELEMENT), text)
    assert result["failed"] == 2 and result["created"] == 0 and result["updated"] == 0


def test_a_plain_member_cannot_create_or_update_through_a_file(client, admin_token):
    org, project, admin = setup(client, admin_token, "Arch tables gate")
    _uid, member = add_member(client, admin, org["id"], project["id"], "member.tables@example.com")
    element = make_element(client, admin, project["id"], "Gate target")
    text = _csv(["code", "description"], [element["unique_code"], "Sneaky."])
    resp = client.post(
        f"{_tier(project, ELEMENT)}/import", params={"dry_run": "false"},
        files={"file": ("records.csv", text.encode("utf-8"), "text/csv")}, headers=auth_headers(member),
    )
    assert resp.status_code == 403
    assert _element_list(client, admin, project["id"])["Gate target"]["description"] == ""


def test_connections_export_and_import_by_element_code_and_port_name(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch tables connections")
    a = make_element(client, token, project["id"], "Node", ports=[{"name": "Out"}])
    b = make_element(client, token, project["id"], "Hub", ports=[{"name": "In"}])
    made = make_connection(client, token, project["id"], a["id"], b["id"], name="Readings", protocol="MQTT", source_port_id=a["ports"][0]["id"])
    rows = _rows(client.get(f"{_tier(project, CONNECTION)}/export", headers=auth_headers(token)))
    assert rows[0]["code"] == made["unique_code"] and rows[0]["source"] == "ELM-001" and rows[0]["target"] == "ELM-002"
    assert rows[0]["source_port"] == "Out" and rows[0]["target_port"] == "" and rows[0]["type"] == "REST API"

    result = _import(client, token, _tier(project, CONNECTION), _csv(
        ["code", "name", "type", "source", "source_port", "target", "target_port", "status"],
        ["", "Commands", "gRPC", "ELM-002", "In", "ELM-001", "Out", "Active"],
        ["", "Missing port", "gRPC", "ELM-002", "Nope", "ELM-001", "", ""],
        ["", "Same end", "gRPC", "ELM-001", "", "ELM-001", "", ""],
        [made["unique_code"], "Readings", "REST API", "ELM-001", "Out", "ELM-002", "In", "Active"],
    ))
    assert (result["created"], result["updated"], result["failed"]) == (1, 1, 2), result
    listed = {c["name"]: c for c in client.get(f"{project_base(project['id'])}/connections", headers=auth_headers(token)).json()}
    assert listed["Commands"]["status"] == "active" and listed["Commands"]["source_port_name"] == "In"
    assert listed["Commands"]["connection_type_name"] == "gRPC" and listed["Commands"]["unique_code"] == "CON-002"
    # The existing connection gained its target port and became Active.
    assert listed["Readings"]["target_element_code"] == "ELM-002" and listed["Readings"]["target_port_name"] == "In"
    assert listed["Readings"]["source_port_name"] == "Out" and listed["Readings"]["status"] == "active"


def test_the_symbol_column_exports_a_name_and_imports_a_name_or_clears_it(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch tables symbol")
    h = auth_headers(token)
    drawing = b'<svg xmlns="http://www.w3.org/2000/svg"><rect/></svg>'
    own = client.post(
        f"{project_base(project['id'])}/symbols", files={"file": ("pump.svg", drawing, "image/svg+xml")},
        data={"name": "Pump"}, headers=h,
    )
    assert own.status_code == 201, own.text
    element = make_element(client, token, project["id"], "Station", symbol_id=own.json()["id"])
    plain = make_element(client, token, project["id"], "Plain")

    rows = {r["name"]: r for r in _rows(client.get(f"{_tier(project, ELEMENT)}/export", headers=h))}
    assert rows["Station"]["symbol"] == "Pump" and rows["Plain"]["symbol"] == ""
    exported = client.get(f"{_tier(project, ELEMENT)}/export", headers=h).content.decode("utf-8-sig")
    result = _import(client, token, _tier(project, ELEMENT), exported)
    assert (result["updated"], result["failed"]) == (0, 0), result

    result = _import(client, token, _tier(project, ELEMENT), _csv(
        ["code", "symbol"], [plain["unique_code"], "Cloud"], [element["unique_code"], ""], ["", "Nonsense"],
    ))
    assert (result["updated"], result["failed"]) == (2, 1), result
    listed = _element_list(client, token, project["id"])
    symbols = {s["name"]: s["id"] for s in client.get(f"{project_base(project['id'])}/symbols", headers=h).json()}
    assert listed["Plain"]["symbol_id"] == symbols["Cloud"] and listed["Station"]["symbol_id"] is None


def test_the_display_note_is_a_column_that_exports_creates_and_updates_apart_from_the_description(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch tables note")
    element = make_element(client, token, project["id"], "Gateway", description="Long text.", display_note="Short line.")
    rows = _rows(client.get(f"{_tier(project, ELEMENT)}/export", headers=auth_headers(token)))
    assert rows[0]["display_note"] == "Short line." and rows[0]["description"] == "Long text."
    exported = client.get(f"{_tier(project, ELEMENT)}/export", headers=auth_headers(token)).content.decode("utf-8-sig")
    result = _import(client, token, _tier(project, ELEMENT), exported)
    assert (result["updated"], result["unchanged"], result["failed"]) == (0, 1, 0)

    result = _import(client, token, _tier(project, ELEMENT), _csv(["code", "display_note"], [element["unique_code"], "Edited line."]))
    assert (result["updated"], result["failed"]) == (1, 0), result
    text = _csv(
        ["code", "name", "type", "display_note"],
        ["", "Created", "Component", "From a file."], ["", "Too long", "Component", "x" * 501],
    )
    result = _import(client, token, _tier(project, ELEMENT), text)
    assert (result["created"], result["failed"]) == (1, 1), result
    current = _element_list(client, token, project["id"])
    assert current["Gateway"]["display_note"] == "Edited line." and current["Gateway"]["description"] == "Long text."
    assert current["Created"]["display_note"] == "From a file."
