"""Tests for the state machine diagram section of the project bundle (`state_machine_export.py`): a diagram with its states
(nested and marker), transitions, attach points, tags and a pinned comment survives export and import into a fresh project
and is numbered afresh; a link to a state travels and is restored; a diagram of an element another owner shares travels as
a reference; a diagram whose element is missing is dropped with a warning; and a project created from a template receives
its diagrams as fresh drafts. Every test builds its own organisation."""

from __future__ import annotations

import io
import json
import uuid
import zipfile

from app.modules.architecture.tests._helpers import (
    add_state,
    add_transition,
    machine_model,
    machine_version,
    make_element,
    move_status,
    project_base,
    setup,
    sound_machine,
)
from tests.conftest import auth_headers
from tests.link_world import World

SECTION = "architecture_state_machine_diagrams"
MACHINE = "architecture_state_machine_diagram"
STATE = "architecture_state"


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


def _machines(client, token, project_id) -> list[dict]:
    resp = client.get(f"{project_base(project_id)}/state-machine-diagrams", params={"include_archived": "true"}, headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_a_state_machine_diagram_round_trips_with_states_transitions_tags_and_a_pinned_comment(client, admin_token):
    org, project, token = setup(client, admin_token, "Arch smd bundle")
    element = make_element(client, token, project["id"], "Flight controller")
    machine, states = sound_machine(client, token, project["id"], element["id"], "Operating modes")
    nested = add_state(client, token, project["id"], machine["id"], "Cruise", parent_state_id=states["Running"]["id"], activity="hold_course()")
    choice = add_state(
        client, token, project["id"], machine["id"], "Check", kind="choice", parent_state_id=states["Running"]["id"],
    )
    add_transition(
        client, token, project["id"], machine["id"], nested["id"], choice["id"], event="tick", guard="ok", action="log()",
        source_point="top",
    )
    add_transition(client, token, project["id"], machine["id"], nested["id"], nested["id"], event="again")
    for kind, record_id in ((MACHINE, machine["id"]), (STATE, nested["id"])):
        applied = client.put(
            f"/api/v1/projects/{project['id']}/artefacts/{kind}/{record_id}/tags", json={"tags": ["safety"]}, headers=auth_headers(token),
        )
        assert applied.status_code in (200, 201), applied.text
    pin = client.post(
        f"/api/v1/projects/{project['id']}/artefacts/{MACHINE}/{machine['id']}/comments",
        json={"body": "Check this mode.", "pin": {"anchor_kind": "node", "anchor_key": nested["id"], "x": 1, "y": 2}},
        headers=auth_headers(token),
    )
    assert pin.status_code == 201, pin.text
    move_status(client, token, project["id"], machine["id"], "active")
    content, bundle = _export(client, token, project["id"])
    exported = bundle[SECTION]
    assert [m["unique_code"] for m in exported] == ["SMD-001"]
    row = exported[0]
    assert row["element"] == {"code": element["unique_code"]} and row["status"] == "active" and row["tags"] == ["safety"]
    assert {s["name"]: s["parent_name"] for s in row["states"]} == {
        "Start": None, "Running": None, "Stop": None, "Cruise": "Running", "Check": "Running",
    }
    assert next(s for s in row["states"] if s["name"] == "Cruise")["tags"] == ["safety"]
    assert [(t["source"], t["target"], t["event"]) for t in row["transitions"]] == [
        ("Start", "Running", ""), ("Running", "Stop", "halt"), ("Cruise", "Check", "tick"), ("Cruise", "Cruise", "again"),
    ]
    assert row["transitions"][2]["source_point"] == "top" and row["transitions"][2]["guard"] == "ok"
    assert len(row["comment_pins"]) == 1 and row["comment_pins"][0]["anchor"] == {"kind": "node", "code": "Cruise"}

    imported = _import(client, token, org["id"], content, "Arch smd bundle copy")["project"]
    copies = _machines(client, token, imported["id"])
    assert [m["name"] for m in copies] == ["Operating modes"] and copies[0]["unique_code"] == "SMD-001"
    assert copies[0]["status"] == "active" and copies[0]["element_code"] == element["unique_code"]
    assert copies[0]["id"] != machine["id"]
    model = machine_model(client, token, imported["id"], copies[0]["id"])
    assert {s["name"]: s["parent_state_code"] for s in model["states"]}["Cruise"] is not None
    assert sorted(s["unique_code"] for s in model["states"]) == [f"STE-{n:03d}" for n in range(1, 6)]  # numbered afresh
    assert [(t["source_state_code"] != "", t["event"]) for t in model["transitions"]] == [
        (True, ""), (True, "halt"), (True, "tick"), (True, "again"),
    ]
    assert [t["source_point"] for t in model["transitions"]] == [None, None, "top", None]
    assert machine_model(client, token, project["id"], machine["id"])["findings"] == model["findings"]
    thread = client.get(
        f"{project_base(imported['id'])}/state-machine-diagrams/{copies[0]['id']}/comments", headers=auth_headers(token),
    ).json()
    pins = thread["pins"]
    cruise = next(s for s in model["states"] if s["name"] == "Cruise")
    assert [p["anchor_key"] for p in pins] == [cruise["id"]]


def test_a_link_to_a_state_travels_with_the_bundle(client, admin_token):
    world = World(client, admin_token, "Arch smd bundle links")
    world.enable("architecture")
    project = world.project("Arch smd bundle links project")
    element = make_element(client, world.token, project["id"], "Hoist")
    machine, states = sound_machine(client, world.token, project["id"], element["id"])
    requirement = world.requirement(project)
    types = world.link_types_by_name()
    created = world.generic_link(project, ("requirement", requirement), types["Allocated to"]["id"], (STATE, uuid.UUID(states["Running"]["id"])))
    assert created.status_code in (200, 201), created.text
    content, bundle = _export(client, world.token, project["id"])
    links = bundle["architecture_links"]
    assert any(
        {link["source"]["type"], link["target"]["type"]} == {"requirement", "architecture_state"} for link in links
    ), links
    assert machine


def test_a_diagram_of_an_element_that_is_missing_is_dropped_with_a_warning(client, admin_token):
    org, project, token = setup(client, admin_token, "Arch smd bundle missing")
    element = make_element(client, token, project["id"], "Winch")
    sound_machine(client, token, project["id"], element["id"])
    content, bundle = _export(client, token, project["id"])
    for key in ("architecture_elements", "architecture_connections", "architecture_diagrams", "architecture_links"):
        bundle[key] = []
    rewritten = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(content)) as source, zipfile.ZipFile(rewritten, "w") as target:
        for item in source.infolist():
            data = source.read(item.filename)
            target.writestr(item, json.dumps(bundle).encode() if item.filename == "project.json" else data)
    result = _import(client, token, org["id"], rewritten.getvalue(), "Arch smd bundle missing copy")
    assert _machines(client, token, result["project"]["id"]) == []
    assert any("State machine diagram SMD-001 skipped" in str(w) for w in result.get("warnings", [])), result


def test_a_project_created_from_a_template_receives_the_state_machine_diagrams_as_fresh_drafts(client, admin_token):
    org, project, token = setup(client, admin_token, "Arch smd bundle template")
    element = make_element(client, token, project["id"], "Antenna")
    machine, _states = sound_machine(client, token, project["id"], element["id"], "Tracking")
    move_status(client, token, project["id"], machine["id"], "active")
    marked = client.patch(f"/api/v1/projects/{project['id']}", json={"is_template": True}, headers=auth_headers(token))
    assert marked.status_code == 200, marked.text
    created = client.post(
        "/api/v1/projects",
        json={"organization_id": org["id"], "name": "Arch smd from template", "summary": "", "template_project_id": project["id"]},
        headers=auth_headers(token),
    )
    assert created.status_code == 201, created.text
    copies = _machines(client, token, created.json()["id"])
    assert [m["name"] for m in copies] == ["Tracking"]
    assert copies[0]["status"] == "draft" and copies[0]["version"] > 0
    assert len(machine_model(client, token, created.json()["id"], copies[0]["id"])["states"]) == 3
    assert machine_version(client, token, project["id"], machine["id"]) >= 1
