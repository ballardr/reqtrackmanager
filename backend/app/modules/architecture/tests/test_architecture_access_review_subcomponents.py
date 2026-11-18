"""The access review of the sub-component switches: where a project switches a record type off (connections, diagrams, state
machine diagrams), no route of the module, no file and no core record route names a record of that type. Every test builds
its own organisation.
"""

from __future__ import annotations

import uuid

from app.modules.architecture.service import (
    CONNECTION_SUBCOMPONENT_KEY,
    DIAGRAM_SUBCOMPONENT_KEY,
    STATE_MACHINE_SUBCOMPONENT_KEY,
)
from app.modules.architecture.tests._helpers import (
    add_state,
    make_connection,
    make_diagram,
    make_element,
    make_machine,
    place,
    project_base,
    setup,
)
from app.modules.architecture.tests._security_sweep import call, fill, routes
from tests.conftest import auth_headers

_HIDDEN = ["OffConnectionName", "OffDiagramName", "OffMachineName", "OffStateName", "OffNoteText"]


def _world(client, admin_token):
    """A project with an element pair, a connection, a diagram with a note and a state machine diagram, each with a name
    from `_HIDDEN`, and then the three record types switched off. Returns `(project, token, ids)`."""
    org, project, token = setup(client, admin_token, f"Review off {uuid.uuid4().hex[:6]}")
    pid = project["id"]
    first = make_element(client, token, pid, "Off first", activate=True)
    second = make_element(client, token, pid, "Off second", activate=True)
    connection = make_connection(client, token, pid, first["id"], second["id"], name=_HIDDEN[0])
    diagram = place(client, token, pid, make_diagram(client, token, pid, _HIDDEN[1]), first["id"], x=0, y=0)
    saved = client.put(
        f"{project_base(pid)}/diagrams/{diagram['id']}/layout",
        json={"version": diagram["version"], "placements": [{"element_id": first["id"], "x": 0, "y": 0}], "notes": [{"text": _HIDDEN[4]}]},
        headers=auth_headers(token),
    )
    assert saved.status_code == 200, saved.text
    machine = make_machine(client, token, pid, first["id"], _HIDDEN[2])
    state = add_state(client, token, pid, machine["id"], _HIDDEN[3], kind="initial")
    for key in (CONNECTION_SUBCOMPONENT_KEY, DIAGRAM_SUBCOMPONENT_KEY, STATE_MACHINE_SUBCOMPONENT_KEY):
        off = client.put(
            f"/api/v1/projects/{pid}/modules/architecture/subcomponents/{key}", json={"enabled": False}, headers=auth_headers(token),
        )
        assert off.status_code == 200, off.text
    ids = {
        "element": first["id"], "connection": connection["id"], "diagram": diagram["id"], "machine": machine["id"],
        "state": state["id"],
    }
    return project, token, ids


def test_a_record_type_switched_off_is_named_by_no_read_route_of_the_module(client, admin_token):
    project, token, ids = _world(client, admin_token)
    failures = []
    for method, path, _route in routes(client.app):
        if method != "GET" or "{project_id}" not in path or "{organization_id}" in path:
            continue
        url = fill(path, {"project_id": project["id"]}, ids)
        resp = call(client, method, url, token)
        named = [h for h in _HIDDEN if h in resp.text]
        if resp.status_code >= 500 or named:
            failures.append(f"GET {url} -> {resp.status_code} {named}")
    assert not failures, "\n".join(failures)


def test_a_record_type_switched_off_is_named_by_no_file_core_route_or_search(client, admin_token):
    project, token, ids = _world(client, admin_token)
    root = f"/api/v1/projects/{project['id']}"
    urls = [f"{project_base(project['id'])}/interchange/json", f"{project_base(project['id'])}/interchange/structurizr"]
    for artefact_type, key in (
        ("architecture_connection", "connection"), ("architecture_diagram", "diagram"),
        ("architecture_state_machine_diagram", "machine"), ("architecture_state", "state"),
    ):
        urls += [f"{root}/artefacts/{artefact_type}/{ids[key]}/{suffix}" for suffix in ("link-graph", "tags", "comments", "activity")]
        urls += [f"{root}/records/{artefact_type}/export?format=csv", f"{root}/records/{artefact_type}/grid"]
    for url in urls:
        resp = client.get(url, headers=auth_headers(token))
        assert resp.status_code < 500, f"{url} -> {resp.status_code}"
        assert not [h for h in _HIDDEN if h in resp.text], f"{url} names a record of a switched-off type: {resp.text[:300]}"
    found = client.post(
        "/api/v1/search", json={"q": "Off", "scope": "project", "project_id": project["id"], "fields": ["id", "title", "description"]},
        headers=auth_headers(token),
    )
    assert found.status_code == 200 and not [h for h in _HIDDEN if h in found.text], found.text


def test_a_sub_component_that_serves_several_types_switches_all_of_them_off(client, admin_token):
    """The state machine sub-component is keyed `architecture_state_machine` but serves the state machine diagram and the state
    types; the core's per-type gate (`artefact_type_enabled_for_project`) follows it, so the core's routes follow too."""
    from app.database import SessionLocal
    from app.modules.registry import artefact_type_enabled_for_project

    project, _token, _ids = _world(client, admin_token)
    with SessionLocal() as db:
        pid = uuid.UUID(project["id"])
        assert artefact_type_enabled_for_project(db, "architecture_element", pid)
        for artefact_type in ("architecture_connection", "architecture_diagram", "architecture_state_machine_diagram", "architecture_state"):
            assert not artefact_type_enabled_for_project(db, artefact_type, pid), artefact_type


def test_an_import_leaves_out_a_record_type_the_project_has_switched_off(client, admin_token):
    """A file made where every type is on carries diagrams; imported into a project that switched diagrams and connections off,
    it adds the elements only and says what it left out."""
    org, source, token = setup(client, admin_token, f"Review import {uuid.uuid4().hex[:6]}")
    first = make_element(client, token, source["id"], "Import first", activate=True)
    second = make_element(client, token, source["id"], "Import second", activate=True)
    make_connection(client, token, source["id"], first["id"], second["id"], name="Import link")
    place(client, token, source["id"], make_diagram(client, token, source["id"], "Import diagram"), first["id"], x=0, y=0)
    exported = client.get(f"{project_base(source['id'])}/interchange/json", headers=auth_headers(token))
    assert exported.status_code == 200
    assert exported.json()["data"]["architecture_diagrams"] and exported.json()["data"]["architecture_connections"]

    from tests.conftest import create_project

    target = create_project(client, token, org["id"], "Import target")
    for key in (CONNECTION_SUBCOMPONENT_KEY, DIAGRAM_SUBCOMPONENT_KEY):
        off = client.put(
            f"/api/v1/projects/{target['id']}/modules/architecture/subcomponents/{key}", json={"enabled": False},
            headers=auth_headers(token),
        )
        assert off.status_code == 200, off.text
    sent = client.post(
        f"{project_base(target['id'])}/interchange/json", content=exported.content,
        headers={**auth_headers(token), "Content-Type": "application/json"},
    )
    assert sent.status_code == 200, sent.text
    report = sent.json()
    assert report["created"]["elements"] == 2
    assert report["created"]["connections"] == 0 and report["created"]["diagrams"] == 0
    assert any("switched off" in w for w in report["warnings"]), report["warnings"]
