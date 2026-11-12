"""Tests for finding elements and connections through the global search and the link finder: by code, name, port
name and protocol; archived and other projects' records stay out. Every test builds its own organisation."""

from __future__ import annotations

from app.modules.architecture.tests._helpers import make_connection, make_element, project_base, setup
from tests.conftest import auth_headers, create_project

ALL_FIELDS = ["id", "title", "description", "ports", "protocol"]


def _search(client, token, project_id: str, text: str, **body):
    resp = client.post(
        "/api/v1/search", json={"q": text, "scope": "project", "project_id": project_id, "fields": ALL_FIELDS, **body},
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["hits"]


def test_elements_are_found_by_name_code_description_and_port_name(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch search elements")
    element = make_element(
        client, token, project["id"], "Telemetry gateway", description="Buffers readings.", ports=[{"name": "ModbusPort"}],
    )
    make_element(client, token, project["id"], "Unrelated")
    for text in ("telemetry", element["unique_code"], "buffers", "modbusport"):
        hits = _search(client, token, project["id"], text)
        assert [h["title"] for h in hits if h["type"] == "architecture_element"] == ["Telemetry gateway"], text
    hit = next(h for h in _search(client, token, project["id"], "telemetry") if h["type"] == "architecture_element")
    assert hit["status_label"] == "Draft" and hit["open_project_id"] == project["id"] and hit["code"] == element["unique_code"]


def test_connections_are_found_by_name_protocol_and_an_unnamed_one_by_code(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch search connections")
    a = make_element(client, token, project["id"], "A")
    b = make_element(client, token, project["id"], "B")
    named = make_connection(client, token, project["id"], a["id"], b["id"], name="Readings feed", protocol="AMQP 1.0")
    unnamed = make_connection(client, token, project["id"], b["id"], a["id"])
    assert [h["title"] for h in _search(client, token, project["id"], "readings") if h["type"] == "architecture_connection"] == ["Readings feed"]
    assert [h["code"] for h in _search(client, token, project["id"], "amqp") if h["type"] == "architecture_connection"] == [named["unique_code"]]
    by_code = _search(client, token, project["id"], unnamed["unique_code"])
    assert [h["title"] for h in by_code if h["type"] == "architecture_connection"] == [unnamed["unique_code"]]


def test_archived_records_and_other_projects_are_left_out(client, admin_token):
    org, project, token = setup(client, admin_token, "Arch search scope")
    h = auth_headers(token)
    other = create_project(client, token, org["id"], "Arch search scope other")
    mine = make_element(client, token, project["id"], "Quasar mine")
    elsewhere = make_element(client, token, other["id"], "Quasar elsewhere")
    archived = make_element(client, token, project["id"], "Quasar archived")
    client.post(f"{project_base(project['id'])}/elements/{archived['id']}/archive", headers=h)
    scoped = _search(client, token, project["id"], "quasar")
    assert {x["title"] for x in scoped if x["type"] == "architecture_element"} == {"Quasar mine"}
    everywhere = _search(client, token, project["id"], "quasar", include_archived=True)
    assert {x["title"] for x in everywhere if x["type"] == "architecture_element"} == {"Quasar mine", "Quasar archived"}
    assert mine["id"] != elsewhere["id"]
