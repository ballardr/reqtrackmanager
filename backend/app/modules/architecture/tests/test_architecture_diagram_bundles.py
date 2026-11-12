"""Tests for the diagram section of the project bundle (`export.py`): a diagram with its element boxes, notes, toggles
(rule types by name, manual members by code), tags and places survives export and import into a fresh project and is
numbered afresh; a box for an element another owner shares travels as a reference (codes only) and is resolved for the
importer; and a project created from a template receives its diagrams as fresh drafts that place only the template's own
elements. Every test builds its own organisation."""

from __future__ import annotations

import io
import json
import zipfile
from typing import Any

from app.modules.architecture.export import reset_for_template
from app.modules.architecture.tests._helpers import (
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
from tests.conftest import auth_headers, create_component_and_category, create_project

DIAGRAM = "architecture_diagram"


def _export(client, token, project_id) -> tuple[bytes, dict]:
    resp = client.get(f"/api/v1/projects/{project_id}/export", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return resp.content, json.loads(zipfile.ZipFile(io.BytesIO(resp.content)).read("project.json"))


def _import(client, token, org_id, content: bytes, name: str) -> dict:
    resp = client.post(
        "/api/v1/projects/import", data={"organization_id": org_id, "name": name},
        files={"file": ("bundle.zip", content, "application/zip")}, headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _diagrams(client, token, project_id) -> dict[str, dict]:
    resp = client.get(f"{project_base(project_id)}/diagrams", params={"include_archived": "true"}, headers=auth_headers(token))
    return {d["name"]: d for d in resp.json()}


def _flow(client, token, project_id):
    sensor = make_element(client, token, project_id, "Sensor", type_name="Sensor")
    firewall = make_element(client, token, project_id, "Firewall")
    cloud = make_element(client, token, project_id, "Cloud", type_name="System")
    link = make_connection(client, token, project_id, sensor["id"], firewall["id"], name="In")
    make_connection(client, token, project_id, firewall["id"], cloud["id"], name="Out")
    return sensor, firewall, cloud, link


def test_a_diagram_round_trips_with_boxes_notes_toggles_tags_and_places_and_is_numbered_afresh(client, admin_token):
    org, project, token = setup(client, admin_token, "Arch diagram bundle")
    h = auth_headers(token)
    base = project_base(project["id"])
    component_id, category_id = create_component_and_category(client, token, project["id"])
    sensor, firewall, cloud, link = _flow(client, token, project["id"])
    types = element_types(client, token, project["id"])
    diagram = make_diagram(
        client, token, project["id"], "Flow", purpose="Sensor to cloud.", connection_detail=True, activate=True,
        scope_element_id=cloud["id"],
    )
    diagram = place_all(client, token, project["id"], diagram, sensor["id"], firewall["id"], cloud["id"])
    saved = client.put(f"{base}/diagrams/{diagram['id']}/layout", json={
        "version": diagram["version"],
        "placements": [
            {"element_id": sensor["id"], "x": 1, "y": 2}, {"element_id": firewall["id"], "x": 300, "y": 2, "collapsed": True},
            {"element_id": cloud["id"], "x": 600, "y": 2},
        ],
        "notes": [{"text": "Edge of trust", "x": 0, "y": -80, "width": 200}],
    }, headers=h).json()
    save_toggles(client, token, project["id"], saved, [{
        "name": "Security", "default_on": False, "element_ids": [firewall["id"]], "connection_ids": [link["id"]],
        "rule": {"element_type_ids": [types["Sensor"]], "domains": ["hardware"], "tags": ["security"]},
    }])
    assert client.put(
        f"/api/v1/projects/{project['id']}/artefacts/{DIAGRAM}/{diagram['id']}/tags", json={"tags": ["context"]}, headers=h,
    ).status_code in (200, 201)
    assert client.put(
        f"/api/v1/projects/{project['id']}/artefacts/{DIAGRAM}/{diagram['id']}/placements",
        json={"placements": [{"component_id": component_id, "category_id": category_id}]}, headers=h,
    ).status_code == 200

    content, project_json = _export(client, token, project["id"])
    (entry,) = project_json["architecture_diagrams"]
    assert entry["unique_code"] == "DGM-001" and entry["scope"] == {"code": cloud["unique_code"]}
    assert [b["code"] for b in entry["boxes"]] == [sensor["unique_code"], firewall["unique_code"], cloud["unique_code"]]
    assert entry["toggles"][0]["rule"]["element_type_names"] == ["Sensor"]
    assert "id" not in json.dumps(entry["toggles"][0]["rule"]).replace("domains", "")  # names, never ids

    copy = _import(client, token, org["id"], content, "Arch diagram bundle copy")["project"]
    (imported,) = _diagrams(client, token, copy["id"]).values()
    assert (imported["name"], imported["status"], imported["connection_detail"], imported["purpose"]) == (
        "Flow", "active", True, "Sensor to cloud.",
    )
    assert imported["unique_code"] == "DGM-001" and imported["project_id"] == copy["id"]
    assert (imported["placement_count"], imported["note_count"], imported["toggle_count"]) == (3, 1, 1)
    assert imported["scope_element_name"] == "Cloud"
    shown = view(client, token, copy["id"], imported["id"])
    boxes = {n["name"]: n for n in shown["nodes"]}
    assert (boxes["Sensor"]["x"], boxes["Firewall"]["collapsed"], boxes["Cloud"]["x"]) == (1, True, 600)
    (toggle,) = shown["toggles"]
    assert (toggle["name"], toggle["default_on"], toggle["on"]) == ("Security", False, False)
    assert len(toggle["element_ids"]) == 1 and len(toggle["connection_ids"]) == 1
    assert toggle["rule"]["domains"] == ["hardware"] and toggle["rule"]["tags"] == ["security"]
    assert len(toggle["rule"]["element_type_ids"]) == 1
    # The imported toggle is switched off by default, so the firewall is bridged exactly as in the source.
    assert shown["notes"][0]["text"] == "Edge of trust"
    tags = client.get(f"/api/v1/projects/{copy['id']}/artefacts/{DIAGRAM}/{imported['id']}/tags", headers=h)
    assert tags.status_code == 200 and "context" in tags.text


def test_a_box_for_an_element_another_project_shares_travels_as_a_reference(client, admin_token):
    org, owner, token = setup(client, admin_token, "Arch diagram bundle shared")
    consumer = create_project(client, token, org["id"], "Arch diagram bundle shared consumer")
    shared = make_element(client, token, owner["id"], "Platform", activate=True)
    mine = make_element(client, token, consumer["id"], "Local app")
    base = project_base(owner["id"])
    collection = make_collection(client, token, base, "Infra", members=[shared["id"]])
    grant(client, token, base, collection["id"], project_id=consumer["id"])
    architect = make_architect(client, token, org["id"], consumer["id"], "arch.diagram.bundleshared@example.com")
    diagram = make_diagram(client, architect, consumer["id"], "Context")
    place_all(client, architect, consumer["id"], diagram, mine["id"], shared["id"])
    content, project_json = _export(client, token, consumer["id"])
    boxes = project_json["architecture_diagrams"][0]["boxes"]
    assert boxes[0]["code"] == mine["unique_code"]
    assert boxes[1]["ref"]["owner_code"] and boxes[1]["ref"]["code"] == shared["unique_code"] and "code" not in boxes[1]
    assert "Platform" not in json.dumps(project_json["architecture_diagrams"])

    # Imported by an administrator, who can read the owner project, the shared box is resolved and kept.
    kept = _import(client, token, org["id"], content, "Arch diagram bundle shared copy")["project"]
    (copy,) = _diagrams(client, token, kept["id"]).values()
    assert copy["placement_count"] == 2


def test_a_template_receives_diagrams_as_fresh_drafts_placing_only_its_own_elements():
    data: dict[str, Any] = {
        "architecture_elements": [{"unique_code": "ELM-001", "status": "active"}],
        "architecture_connections": [],
        "architecture_diagrams": [
            {
                "unique_code": "DGM-001", "name": "Context", "status": "active", "is_archived": False,
                "created_by_email": "a@example.com", "created_at": "2026-01-01T00:00:00Z",
                "scope": {"ref": {"owner": "project", "owner_code": "OTH", "code": "ELM-009"}},
                "boxes": [{"code": "ELM-001"}, {"code": "ELM-404"}, {"ref": {"owner": "project", "owner_code": "OTH", "code": "ELM-009"}}],
                "notes": [{"text": "kept"}],
                "toggles": [{
                    "name": "T", "elements": [{"code": "ELM-001"}, {"code": "ELM-404"}], "connection_codes": ["CON-001"],
                    "rule": {},
                }],
            },
            {"unique_code": "DGM-002", "name": "Old", "is_archived": True, "boxes": [], "notes": [], "toggles": []},
        ],
        "architecture_links": [],
        "architecture_collections": [],
    }
    reset_for_template(data)
    (diagram,) = data["architecture_diagrams"]
    assert diagram["status"] == "draft" and diagram["created_by_email"] is None and diagram["scope"] is None
    assert diagram["boxes"] == [{"code": "ELM-001"}] and diagram["notes"] == [{"text": "kept"}]
    assert diagram["toggles"][0]["elements"] == [{"code": "ELM-001"}] and diagram["toggles"][0]["connection_codes"] == []
