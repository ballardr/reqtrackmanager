"""Tests for the JSON interchange file and the Structurizr DSL export: the round trip into another project, the preview
that stores nothing, what the file leaves out, the limits and version rule, who may import, an unresolvable end being
reported, and the DSL's structure, escaping and exclusions. Every test builds its own organisation."""

from __future__ import annotations

import json

from sqlalchemy import select

from app.database import SessionLocal
from app.models.audit import AuditEvent
from app.modules.architecture.interchange import FORMAT, MAX_BYTES, VERSION
from app.modules.architecture.tests._helpers import (
    add_member,
    make_architect,
    make_connection,
    make_diagram,
    make_element,
    place_all,
    project_base,
    save_toggles,
    setup,
    sound_machine,
)
from tests.conftest import auth_headers, create_project


def _get(client, token, project_id, path, **params):
    resp = client.get(f"{project_base(project_id)}/interchange/{path}", params=params, headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return resp


def _post(client, token, project_id, path, body, *, expect=200):
    content = body if isinstance(body, bytes) else json.dumps(body).encode()
    resp = client.post(
        f"{project_base(project_id)}/interchange/{path}", content=content,
        headers={**auth_headers(token), "Content-Type": "application/json"},
    )
    assert resp.status_code == expect, resp.text
    return resp.json()


def _count(client, token, project_id, kind) -> int:
    return len(client.get(f"{project_base(project_id)}/{kind}", headers=auth_headers(token)).json())


def _scene(client, token, project_id):
    parent = make_element(client, token, project_id, "Telemetry", type_name="Service")
    child = make_element(client, token, project_id, "Encoder", type_name="Service", parent_id=parent["id"])
    outside = make_element(client, token, project_id, "Cloud", type_name="Service")
    link = make_connection(client, token, project_id, child["id"], outside["id"], protocol="v2")
    diagram = make_diagram(client, token, project_id, "Context", activate=True)
    diagram = place_all(client, token, project_id, diagram, parent["id"], outside["id"])
    save_toggles(client, token, project_id, diagram, [{"name": "Detail", "default_on": False, "element_ids": [child["id"]]}])
    machine, _states = sound_machine(client, token, project_id, child["id"])
    return parent, child, outside, link, diagram, machine


# --- JSON file ----------------------------------------------------------------------------


def test_the_file_round_trips_into_another_project_and_the_preview_stores_nothing(client, admin_token):
    org, source, token = setup(client, admin_token, "Interchange round trip")
    target = create_project(client, token, org["id"], "Interchange target")
    _scene(client, token, source["id"])

    document = _get(client, token, source["id"], "json").json()
    assert document["format"] == FORMAT and document["version"] == VERSION
    assert [e["name"] for e in document["data"]["architecture_elements"]] == ["Telemetry", "Encoder", "Cloud"]

    preview = _post(client, token, target["id"], "json/preview", document)
    assert preview["created"]["elements"] == 3 and preview["created"]["connections"] == 1
    assert preview["created"]["diagrams"] == 1 and preview["created"]["state_machine_diagrams"] == 1
    assert preview["created"]["states"] == 3 and preview["created"]["transitions"] == 2
    assert _count(client, token, target["id"], "elements") == 0

    done = _post(client, token, target["id"], "json", document)
    assert done["created"] == preview["created"]
    elements = {e["name"]: e for e in client.get(f"{project_base(target['id'])}/elements", headers=auth_headers(token)).json()}
    assert set(elements) == {"Telemetry", "Encoder", "Cloud"}
    assert elements["Encoder"]["parent_id"] == elements["Telemetry"]["id"]
    (connection,) = client.get(f"{project_base(target['id'])}/connections", headers=auth_headers(token)).json()
    assert connection["protocol"] == "v2"
    (diagram,) = client.get(f"{project_base(target['id'])}/diagrams", headers=auth_headers(token)).json()
    assert (diagram["placement_count"], diagram["toggle_count"], diagram["status"]) == (2, 1, "active")
    # The records are numbered in the target, not carried over, and the source is unchanged.
    assert _count(client, token, source["id"], "elements") == 3

    with SessionLocal() as db:
        events = list(db.scalars(select(AuditEvent).where(AuditEvent.entity_type == "architecture_interchange")))
    detail = events[0].detail or {}
    assert len(events) == 1 and detail["created"]["elements"] == 3
    assert "Telemetry" not in json.dumps(detail)


def test_the_file_carries_no_comments_no_authors_and_no_requirement_links_or_grants(client, admin_token):
    _org, project, token = setup(client, admin_token, "Interchange leaves out")
    parent, _child, _outside, _link, _diagram, _machine = _scene(client, token, project["id"])
    resp = client.post(
        f"{project_base(project['id'])}/elements/{parent['id']}/comments", json={"body": "Secret discussion"}, headers=auth_headers(token),
    )
    group = client.post(f"/api/v1/projects/{project['id']}/groups", json={"name": "Owners"}, headers=auth_headers(token)).json()
    owned = client.put(
        f"{project_base(project['id'])}/elements/{parent['id']}",
        json={"version": parent["version"], "owner": {"type": "project_group", "id": group["id"]}}, headers=auth_headers(token),
    )
    assert owned.status_code == 200, owned.text
    text = _get(client, token, project["id"], "json").text
    assert "_email" not in text and "@" not in text and '"owner"' not in text and "Owners" not in text
    assert "Secret discussion" not in text or resp.status_code >= 400
    assert "comments" not in text and "architecture_links" not in text and "architecture_collections" not in text
    assert "attachment" in _get(client, token, project["id"], "json").headers["content-disposition"]


def test_a_file_of_another_format_an_unknown_major_a_bad_shape_or_too_much_is_refused_whole(client, admin_token):
    org, project, token = setup(client, admin_token, "Interchange refused")
    target = create_project(client, token, org["id"], "Interchange refused target")
    good = _get(client, token, project["id"], "json").json()
    _post(client, token, target["id"], "json", {**good, "version": "2.0"}, expect=422)
    _post(client, token, target["id"], "json", {**good, "format": "other"}, expect=422)
    _post(client, token, target["id"], "json", b"not json", expect=422)
    _post(client, token, target["id"], "json", {**good, "version": "1.9", "data": {}}, expect=200)
    _post(client, token, target["id"], "json", {**good, "data": {"architecture_elements": [{"unique_code": "ELM-001"}]}}, expect=422)
    _post(client, token, target["id"], "json", {**good, "data": {"architecture_elements": "no"}}, expect=422)
    _post(client, token, target["id"], "json", {**good, "data": {"architecture_elements": [{"name": "A"}]}}, expect=422)
    deep: object = "x"
    for _ in range(60):
        deep = [deep]
    _post(client, token, target["id"], "json", {**good, "extra": deep}, expect=422)
    _post(client, token, target["id"], "json", b" " * (MAX_BYTES + 1), expect=413)
    assert _count(client, token, target["id"], "elements") == 0


def test_an_end_that_cannot_be_resolved_is_reported_and_the_connection_dropped(client, admin_token):
    _org, project, token = setup(client, admin_token, "Interchange unresolved")
    document = {
        "format": FORMAT, "version": VERSION, "data": {
            "architecture_elements": [{"unique_code": "ELM-001", "name": "Local", "type_name": "Service"}],
            "architecture_connections": [{
                "unique_code": "CON-001", "type_name": "REST API", "source_code": "ELM-001",
                "target_ref": {"owner": "project", "owner_code": "NOPE", "code": "ELM-009"},
            }],
        },
    }
    report = _post(client, token, project["id"], "json", document)
    assert report["created"]["elements"] == 1 and report["created"]["connections"] == 0
    assert any("CON-001" in w for w in report["warnings"])


def test_only_an_architect_who_is_also_an_architecture_admin_may_import_but_a_member_may_export(client, admin_token):
    org, project, token = setup(client, admin_token, "Interchange roles")
    _scene(client, token, project["id"])
    document = _get(client, token, project["id"], "json").json()
    _user, member = add_member(client, token, org["id"], project["id"], "interchange.member@example.com")
    architect = make_architect(client, token, org["id"], project["id"], "interchange.architect@example.com")
    assert client.get(f"{project_base(project['id'])}/interchange/json", headers=auth_headers(member)).status_code == 200
    _post(client, member, project["id"], "json", document, expect=403)
    _post(client, architect, project["id"], "json/preview", document, expect=403)
    _post(client, architect, project["id"], "json", document, expect=403)


# --- Structurizr DSL ----------------------------------------------------------------------


def test_the_dsl_has_the_model_the_relationships_and_one_view_per_diagram_and_is_repeatable(client, admin_token):
    _org, project, token = setup(client, admin_token, "Structurizr basic")
    parent, child, outside, link, diagram, _machine = _scene(client, token, project["id"])
    text = _get(client, token, project["id"], "structurizr").text
    assert text.startswith("// System Architecture export")
    assert f'workspace "{project["name"]}"' in text
    assert 'e_elm001 = softwareSystem "Telemetry"' in text and 'e_elm002 = container "Encoder"' in text
    assert f'e_elm002 -> e_elm003 "{link["name"] or "REST API"}" "v2"' in text
    assert f'"code" "{link["unique_code"]}"' in text and '"port' not in text
    assert 'systemLandscape "DGM-001" "DGM-001 Context"' in text and "include e_elm001" in text and "include e_elm003" in text
    assert text.count("{") == text.count("}")
    assert _get(client, token, project["id"], "structurizr").text == text
    assert child["unique_code"] and parent["unique_code"] and outside["unique_code"] and diagram["id"]


def test_the_dsl_names_neither_a_retired_element_nor_a_hidden_box_and_cannot_be_broken_by_a_name(client, admin_token):
    _org, project, token = setup(client, admin_token, "Structurizr exclusions")
    nasty = make_element(client, token, project["id"], 'Gate "A"\nview x {', type_name="Service")
    kept = make_element(client, token, project["id"], "Kept", type_name="Service")
    gone = make_element(client, token, project["id"], "Retired one", type_name="Service")
    make_connection(client, token, project["id"], nasty["id"], gone["id"])
    record = gone
    for step in ("proposed", "active", "retired"):
        resp = client.post(
            f"{project_base(project['id'])}/elements/{gone['id']}/status", json={"version": record["version"], "status": step},
            headers=auth_headers(token),
        )
        assert resp.status_code == 200, resp.text
        record = resp.json()
    text = _get(client, token, project["id"], "structurizr").text
    assert "\nview x {" not in text and 'Gate \\"A\\" view x {' in text
    assert kept["unique_code"] and "Kept" in text and "Retired one" not in text and gone["unique_code"] + '"' not in text
    assert "1 connection(s) with an end this project does not own or that is retired" in text


def test_a_diagram_view_leaves_out_what_a_toggle_hides_and_a_mixed_diagram_is_rolled_up(client, admin_token):
    _org, project, token = setup(client, admin_token, "Structurizr views")
    parent, child, outside, _link, diagram, _machine = _scene(client, token, project["id"])
    mixed = make_diagram(client, token, project["id"], "Mixed")
    place_all(client, token, project["id"], mixed, child["id"], outside["id"])
    only = _get(client, token, project["id"], "structurizr", diagram_id=diagram["id"]).text
    assert "DGM-002" not in only and "include e_elm001" in only
    both = _get(client, token, project["id"], "structurizr").text
    assert "DGM-002 mixes levels" in both
    siblings = make_diagram(client, token, project["id"], "Inside")
    inner = make_element(client, token, project["id"], "Decoder", type_name="Service", parent_id=parent["id"])
    place_all(client, token, project["id"], siblings, child["id"], inner["id"])
    assert 'container e_elm001 "DGM-003"' in _get(client, token, project["id"], "structurizr").text
