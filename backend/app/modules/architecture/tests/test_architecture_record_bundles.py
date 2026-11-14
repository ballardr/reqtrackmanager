"""Tests for the record sections of the project bundle (`export.py`): elements (tree, ports, owner, status, tags,
places), connections (ends and ports by code and name) and the links between them survive export and import into a
fresh project, a record is numbered afresh, an unmatched type is created rather than dropped, and a project created
from a template receives its elements and connections as fresh drafts. Every test builds its own organisation."""

from __future__ import annotations

import io
import json
import uuid
import zipfile
from typing import Any

from app.database import SessionLocal
from app.modules.architecture.export import reset_for_template
from app.modules.architecture.tests._helpers import (
    add_member,
    connection_types,
    make_connection,
    make_element,
    project_base,
    setup,
)
from app.services import relationships
from tests.conftest import auth_headers, create_component_and_category

ELEMENT = "architecture_element"
CONNECTION = "architecture_connection"


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


def _lists(client, token, project_id) -> tuple[dict[str, dict], dict[str, dict]]:
    h = auth_headers(token)
    base = project_base(project_id)
    elements = {e["name"]: e for e in client.get(f"{base}/elements", params={"include_archived": "true"}, headers=h).json()}
    connections = {c["name"]: c for c in client.get(f"{base}/connections", params={"include_archived": "true"}, headers=h).json()}
    return elements, connections


def test_elements_connections_tags_places_and_links_round_trip_and_are_numbered_afresh(client, admin_token):
    org, project, token = setup(client, admin_token, "Arch record bundle")
    h = auth_headers(token)
    base = project_base(project["id"])
    component_id, category_id = create_component_and_category(client, token, project["id"])
    user_id, _t = add_member(client, token, org["id"], project["id"], "owner.bundle@example.com")
    own_type = client.post(f"{base}/element-types", json={"name": "Local block", "shape": "chip"}, headers=h).json()
    spi = connection_types(client, token, project["id"])["SPI"]

    root = make_element(client, token, project["id"], "Platform", type_name="System", activate=True, owner={"type": "user", "id": user_id})
    board = make_element(
        client, token, project["id"], "Main board", type_name="Board", parent_id=root["id"], display_note="Drives the bus.",
        ports=[{"name": "Main", "direction": "in", "connection_type_id": spi}, {"name": "Debug"}],
    )
    local = client.post(f"{base}/elements", json={"name": "Local", "element_type_id": own_type["id"], "parent_id": board["id"]}, headers=h).json()
    gone = make_element(client, token, project["id"], "Old unit")
    client.post(f"{base}/elements/{gone['id']}/archive", headers=h)
    connection = make_connection(
        client, token, project["id"], board["id"], local["id"], name="Bus", protocol="9600 baud", type_name="SPI",
        source_port_id=board["ports"][0]["id"], activate=True,
    )
    tagged = client.put(
        f"/api/v1/projects/{project['id']}/artefacts/{ELEMENT}/{board['id']}/tags", json={"tags": ["hardware"]}, headers=h,
    )
    assert tagged.status_code in (200, 201), tagged.text
    place = client.put(
        f"/api/v1/projects/{project['id']}/artefacts/{ELEMENT}/{board['id']}/placements",
        json={"placements": [{"component_id": component_id, "category_id": category_id}]}, headers=h,
    )
    assert place.status_code == 200, place.text
    with SessionLocal() as db:
        relationships.create_link(
            db, source_type=ELEMENT, source_id=uuid.UUID(root["id"]), target_type=CONNECTION,
            target_id=uuid.UUID(connection["id"]), link_type_id=None, created_by=uuid.UUID(user_id), enforce_rules=False,
            project_id=uuid.UUID(project["id"]),
        )
        db.commit()

    content, project_json = _export(client, token, project["id"])
    assert [e["unique_code"] for e in project_json["architecture_elements"]] == ["ELM-001", "ELM-002", "ELM-003", "ELM-004"]
    assert len(project_json["architecture_links"]) == 1
    imported = _import(client, token, org["id"], content, "Arch record bundle copy")
    copy_id = imported["project"]["id"]
    elements, connections = _lists(client, token, copy_id)

    assert set(elements) == {"Platform", "Main board", "Local", "Old unit"}
    assert elements["Platform"]["status"] == "active" and elements["Platform"]["owner"]["id"] == user_id
    assert elements["Main board"]["parent_id"] == elements["Platform"]["id"]
    assert elements["Main board"]["display_note"] == "Drives the bus." and elements["Platform"]["display_note"] == ""
    assert elements["Local"]["parent_id"] == elements["Main board"]["id"] and elements["Local"]["element_type_name"] == "Local block"
    assert [(p["name"], p["direction"], p["connection_type_name"]) for p in elements["Main board"]["ports"]] == [
        ("Main", "in", "SPI"), ("Debug", "both", None),
    ]
    assert elements["Old unit"]["is_archived"] is True
    assert len({e["unique_code"] for e in elements.values()}) == 4 and elements["Platform"]["unique_code"].startswith("ELM-")
    bus = connections["Bus"]
    assert (bus["source_element_id"], bus["target_element_id"]) == (elements["Main board"]["id"], elements["Local"]["id"])
    assert (bus["source_port_name"], bus["target_port_id"], bus["status"], bus["protocol"]) == ("Main", None, "active", "9600 baud")

    h_copy = auth_headers(token)
    tags = client.get(f"/api/v1/projects/{copy_id}/artefacts/{ELEMENT}/{elements['Main board']['id']}/tags", headers=h_copy).json()
    assert [t["name"] for t in tags["tags"]] == ["hardware"]
    places = client.get(f"/api/v1/projects/{copy_id}/artefacts/{ELEMENT}/{elements['Main board']['id']}/placements", headers=h_copy).json()
    assert len(places["placements"]) == 1
    graph = client.get(
        f"/api/v1/projects/{copy_id}/artefacts/{ELEMENT}/{elements['Platform']['id']}/link-graph", headers=h_copy,
    ).json()
    assert any(n["id"] == bus["id"] for n in graph["nodes"])

    # The copy's counters continue after the imported records.
    fresh = make_element(client, token, copy_id, "After import")
    assert fresh["unique_code"] == "ELM-005"


def test_a_type_the_target_lacks_is_created_and_a_record_keeps_it(client, admin_token):
    org, project, token = setup(client, admin_token, "Arch record bundle type")
    h = auth_headers(token)
    own = client.post(f"{project_base(project['id'])}/element-types", json={"name": "Vanishing type"}, headers=h).json()
    client.post(f"{project_base(project['id'])}/elements", json={"name": "Typed", "element_type_id": own["id"]}, headers=h)
    content, project_json = _export(client, token, project["id"])
    # Drop the type from the bundle's vocabulary section, as if the source never listed it.
    project_json["architecture_project_element_types"] = []
    patched = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(content)) as src, zipfile.ZipFile(patched, "w") as out:
        for item in src.infolist():
            out.writestr(item, json.dumps(project_json) if item.filename == "project.json" else src.read(item.filename))
    imported = _import(client, token, org["id"], patched.getvalue(), "Arch record bundle type copy")
    elements, _connections = _lists(client, token, imported["project"]["id"])
    assert elements["Typed"]["element_type_name"] == "Vanishing type"
    assert any("Vanishing type" in w for w in imported.get("warnings", []))


def test_a_connection_whose_element_is_missing_is_skipped_with_a_warning(client, admin_token):
    org, project, token = setup(client, admin_token, "Arch record bundle skip")
    a = make_element(client, token, project["id"], "A")
    b = make_element(client, token, project["id"], "B")
    make_connection(client, token, project["id"], a["id"], b["id"], name="Orphan-to-be")
    content, project_json = _export(client, token, project["id"])
    project_json["architecture_elements"] = [e for e in project_json["architecture_elements"] if e["name"] != "B"]
    patched = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(content)) as src, zipfile.ZipFile(patched, "w") as out:
        for item in src.infolist():
            out.writestr(item, json.dumps(project_json) if item.filename == "project.json" else src.read(item.filename))
    imported = _import(client, token, org["id"], patched.getvalue(), "Arch record bundle skip copy")
    elements, connections = _lists(client, token, imported["project"]["id"])
    assert set(elements) == {"A"} and connections == {}
    assert any("CON-001" in w for w in imported.get("warnings", []))


def test_template_reset_returns_records_to_fresh_drafts_and_drops_what_cannot_stand_alone():
    data: dict[str, Any] = {
        "architecture_elements": [
            {"unique_code": "ELM-001", "name": "Kept", "status": "active", "created_by_email": "a@x", "is_archived": False},
            {"unique_code": "ELM-002", "name": "Archived", "status": "active", "is_archived": True},
        ],
        "architecture_connections": [
            {"unique_code": "CON-001", "source_code": "ELM-001", "target_code": "ELM-002", "status": "active"},
            {"unique_code": "CON-002", "source_code": "ELM-001", "target_code": "ELM-001", "status": "active"},
        ],
        "architecture_links": [
            {"source": {"type": ELEMENT, "ref": "ELM-002"}, "target": {"type": "requirement", "ref": "REQ-001"}},
            {"source": {"type": ELEMENT, "ref": "ELM-001"}, "target": {"type": "requirement", "ref": "REQ-001"}},
            {"source": {"type": CONNECTION, "ref": "CON-001"}, "target": {"type": "requirement", "ref": "REQ-001"}},
        ],
    }
    reset_for_template(data)
    assert [e["unique_code"] for e in data["architecture_elements"]] == ["ELM-001"]
    assert data["architecture_elements"][0]["status"] == "draft" and data["architecture_elements"][0]["created_by_email"] is None
    assert [c["unique_code"] for c in data["architecture_connections"]] == ["CON-002"]
    assert [link["source"]["ref"] for link in data["architecture_links"]] == ["ELM-001"]


def test_a_project_created_from_a_template_receives_elements_as_drafts(client, admin_token):
    org, project, token = setup(client, admin_token, "Arch record template")
    h = auth_headers(token)
    a = make_element(client, token, project["id"], "Starter A", activate=True, ports=[{"name": "Out"}])
    b = make_element(client, token, project["id"], "Starter B", parent_id=a["id"])
    make_connection(client, token, project["id"], a["id"], b["id"], name="Starter link", activate=True)
    assert client.patch(f"/api/v1/projects/{project['id']}", json={"is_template": True}, headers=h).status_code == 200
    created = client.post(
        "/api/v1/projects",
        json={"organization_id": org["id"], "name": "Arch record template child", "summary": "", "template_project_id": project["id"]},
        headers=h,
    )
    assert created.status_code == 201, created.text
    elements, connections = _lists(client, token, created.json()["id"])
    assert set(elements) == {"Starter A", "Starter B"} and {e["status"] for e in elements.values()} == {"draft"}
    assert elements["Starter B"]["parent_id"] == elements["Starter A"]["id"] and elements["Starter A"]["ports"][0]["name"] == "Out"
    assert connections["Starter link"]["status"] == "draft"


def test_a_bundle_note_is_cut_to_the_cap_and_a_bundle_without_the_field_gives_an_empty_note():
    from app.modules.architecture.enums import DISPLAY_NOTE_MAX
    from app.modules.architecture.export import _display_note

    assert _display_note({"display_note": "x" * (DISPLAY_NOTE_MAX + 50)}) == "x" * DISPLAY_NOTE_MAX
    assert _display_note({}) == "" and _display_note({"display_note": None}) == ""


def test_dismissed_allocations_round_trip_and_a_dismissal_still_applies_after_the_import(client, admin_token):
    org, project, token = setup(client, admin_token, "Arch dismissal bundle")
    h = auth_headers(token)
    component_id, category_id = create_component_and_category(client, token, project["id"])
    requirement = client.post(
        f"/api/v1/projects/{project['id']}/requirements",
        json={"name": "Req", "component_id": component_id, "category_id": category_id}, headers=h,
    )
    assert requirement.status_code == 201, requirement.text
    element = make_element(client, token, project["id"], "Gateway")
    placed = client.put(
        f"/api/v1/projects/{project['id']}/artefacts/{ELEMENT}/{element['id']}/placements",
        json={"placements": [{"component_id": component_id}]}, headers=h,
    )
    assert placed.status_code == 200, placed.text
    pair = {"requirement_id": requirement.json()["id"], "element_id": element["id"]}
    assert client.post(f"{project_base(project['id'])}/allocation/dismiss", json=pair, headers=h).status_code == 204

    content, bundle = _export(client, token, project["id"])
    exported = bundle["architecture_allocation_dismissals"]
    assert [(e["requirement_code"], e["element_code"]) for e in exported] == [(requirement.json()["unique_code"], "ELM-001")]
    imported = _import(client, token, org["id"], content, "Dismissal copy")["project"]
    new_requirement = client.get(f"/api/v1/projects/{imported['id']}/requirements", headers=h).json()
    new_requirement = (new_requirement["items"] if isinstance(new_requirement, dict) else new_requirement)[0]
    view = client.get(f"{project_base(imported['id'])}/requirements/{new_requirement['id']}/allocation", headers=h).json()
    assert view["suggested"] == [] and [p["element"]["unique_code"] for p in view["dismissed"]] == ["ELM-001"]
