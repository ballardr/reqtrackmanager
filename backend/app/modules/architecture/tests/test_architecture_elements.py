"""Tests for elements and their ports: creation and codes, the Architect gate, tree rules (parent, cycle, depth),
the version lock, retire and delete rules, owner validation, list filters, audit events and tenant isolation.
Every test builds its own organisation."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.database import SessionLocal
from app.models.audit import AuditEvent
from app.modules.architecture.models import ArchitectureElement
from app.modules.architecture.records import MAX_DEPTH
from app.modules.architecture.tests._helpers import (
    add_member,
    element_types,
    make_architect,
    make_connection,
    make_element,
    project_base,
    put_element,
    setup,
)
from tests.conftest import auth_headers, create_org_admin_in, create_project


def test_an_element_is_numbered_per_project_and_starts_draft_or_active(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch element create")
    first = make_element(client, token, project["id"], "Edge gateway", description="Receives sensor data.")
    second = make_element(client, token, project["id"], "Cloud API", type_name="Service", activate=True)
    assert (first["unique_code"], first["status"], first["version"]) == ("ELM-001", "draft", 1)
    assert (second["unique_code"], second["status"], second["element_type_name"]) == ("ELM-002", "active", "Service")
    assert first["description"] == "Receives sensor data." and first["parent_id"] is None and first["ports"] == []


def test_ports_can_be_created_with_the_element_and_must_have_distinct_names(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch element ports")
    h = auth_headers(token)
    made = make_element(client, token, project["id"], "Board", ports=[{"name": "Main", "direction": "in"}, {"name": "Debug"}])
    assert [(p["name"], p["direction"]) for p in made["ports"]] == [("Main", "in"), ("Debug", "both")]
    make_element(client, token, project["id"], "Dup", ports=[{"name": "A"}, {"name": "a"}], expect=400)

    base = f"{project_base(project['id'])}/elements/{made['id']}/ports"
    assert client.post(base, json={"name": "MAIN"}, headers=h).status_code == 400
    added = client.post(base, json={"name": "Power", "direction": "out"}, headers=h)
    assert added.status_code == 201 and added.json()["sort_order"] == 2
    again = client.get(f"{project_base(project['id'])}/elements/{made['id']}", headers=h).json()
    assert again["version"] == made["version"] + 1 and len(again["ports"]) == 3


def test_a_port_can_be_renamed_retyped_cleared_and_removed(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch port edit")
    h = auth_headers(token)
    types = client.get(f"{project_base(project['id'])}/connection-types", headers=h).json()
    spi = next(t for t in types if t["name"] == "SPI")
    element = make_element(client, token, project["id"], "Chip", ports=[{"name": "Bus"}])
    port = element["ports"][0]
    url = f"{project_base(project['id'])}/elements/{element['id']}/ports/{port['id']}"

    updated = client.put(url, json={"name": "SPI bus", "direction": "out", "connection_type_id": spi["id"]}, headers=h)
    assert updated.status_code == 200 and updated.json()["connection_type_name"] == "SPI"
    cleared = client.put(url, json={"connection_type_id": None}, headers=h)
    assert cleared.json()["connection_type_id"] is None and cleared.json()["name"] == "SPI bus"
    assert client.delete(url, headers=h).status_code == 204
    assert client.delete(url, headers=h).status_code == 404


def test_a_port_a_connection_uses_cannot_be_removed(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch port in use")
    h = auth_headers(token)
    a = make_element(client, token, project["id"], "A", ports=[{"name": "Out"}])
    b = make_element(client, token, project["id"], "B")
    make_connection(client, token, project["id"], a["id"], b["id"], source_port_id=a["ports"][0]["id"])
    resp = client.delete(f"{project_base(project['id'])}/elements/{a['id']}/ports/{a['ports'][0]['id']}", headers=h)
    assert resp.status_code == 409


def test_only_an_architect_or_an_admin_changes_elements(client, admin_token):
    org, project, admin = setup(client, admin_token, "Arch element gate")
    _uid, member = add_member(client, admin, org["id"], project["id"], "plain.arch@example.com")
    architect = make_architect(client, admin, org["id"], project["id"], "architect.arch@example.com")
    element = make_element(client, admin, project["id"], "Gate target")
    body = {"name": "Nope", "element_type_id": element["element_type_id"]}
    base = project_base(project["id"])

    assert client.post(f"{base}/elements", json=body, headers=auth_headers(member)).status_code == 403
    assert client.put(f"{base}/elements/{element['id']}", json={"version": 1, "name": "x"}, headers=auth_headers(member)).status_code == 403
    assert client.delete(f"{base}/elements/{element['id']}", headers=auth_headers(member)).status_code == 403
    # Any member may read.
    assert client.get(f"{base}/elements", headers=auth_headers(member)).status_code == 200
    assert client.get(f"{base}/elements/{element['id']}", headers=auth_headers(member)).status_code == 200
    # An architect may write.
    assert client.post(f"{base}/elements", json=body, headers=auth_headers(architect)).status_code == 201


def test_a_disabled_module_or_sub_component_is_not_found(client, admin_token):
    org, token = create_org_admin_in(client, admin_token, "Arch element disabled")
    project = create_project(client, token, org["id"], "Arch element disabled project")
    assert client.get(f"{project_base(project['id'])}/elements", headers=auth_headers(token)).status_code == 404


def test_a_child_sits_under_a_parent_and_the_parent_must_be_in_the_project(client, admin_token):
    org, project, token = setup(client, admin_token, "Arch element parent")
    other = create_project(client, token, org["id"], "Arch element parent other")
    parent = make_element(client, token, project["id"], "Parent", type_name="System")
    child = make_element(client, token, project["id"], "Child", parent_id=parent["id"])
    foreign = make_element(client, token, other["id"], "Foreign")
    assert child["parent_id"] == parent["id"]
    make_element(client, token, project["id"], "Bad", parent_id=foreign["id"], expect=400)
    make_element(client, token, project["id"], "Missing", parent_id=str(uuid.uuid4()), expect=400)
    listed = client.get(f"{project_base(project['id'])}/elements", params={"parent_id": parent["id"]}, headers=auth_headers(token)).json()
    assert [e["id"] for e in listed] == [child["id"]]
    everything = client.get(f"{project_base(project['id'])}/elements", headers=auth_headers(token)).json()
    assert next(e for e in everything if e["id"] == parent["id"])["child_count"] == 1


def test_a_move_cannot_make_a_cycle(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch element cycle")
    a = make_element(client, token, project["id"], "A")
    b = make_element(client, token, project["id"], "B", parent_id=a["id"])
    c = make_element(client, token, project["id"], "C", parent_id=b["id"])
    put_element(client, token, project["id"], a, expect=400, parent_id=a["id"])
    put_element(client, token, project["id"], a, expect=400, parent_id=c["id"])
    moved = put_element(client, token, project["id"], c, parent_id=a["id"])
    assert moved["parent_id"] == a["id"]
    top = put_element(client, token, project["id"], moved, parent_id=None)
    assert top["parent_id"] is None


def test_the_tree_is_at_most_twelve_levels_deep_and_a_move_counts_the_subtree(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch element depth")
    parent_id = None
    chain = []
    for level in range(MAX_DEPTH):
        element = make_element(client, token, project["id"], f"Level {level}", parent_id=parent_id)
        chain.append(element)
        parent_id = element["id"]
    make_element(client, token, project["id"], "Too deep", parent_id=parent_id, expect=400)
    # A separate root with a child cannot be moved under the deepest level either.
    root = make_element(client, token, project["id"], "Other root")
    make_element(client, token, project["id"], "Other child", parent_id=root["id"])
    put_element(client, token, project["id"], root, expect=400, parent_id=chain[-1]["id"])
    put_element(client, token, project["id"], root, parent_id=chain[-3]["id"])


def test_a_stale_version_is_refused_and_an_edit_advances_it(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch element version")
    element = make_element(client, token, project["id"], "Versioned")
    edited = put_element(client, token, project["id"], element, name="Renamed", description="New text.")
    assert (edited["name"], edited["version"]) == ("Renamed", 2)
    stale = put_element(client, token, project["id"], element, expect=409, name="Lost update")
    assert "changed by someone else" in stale["detail"]
    unchanged = put_element(client, token, project["id"], edited, name="Renamed")
    assert unchanged["version"] == 2  # a save with no change does not advance the counter


def test_the_element_type_must_be_one_the_project_offers_and_a_used_type_is_not_deleted(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch element type")
    h = auth_headers(token)
    base = project_base(project["id"])
    make_element(client, token, project["id"], "Typed", type_name="Board")
    bad = client.post(f"{base}/elements", json={"name": "No type", "element_type_id": str(uuid.uuid4())}, headers=h)
    assert bad.status_code == 400
    own = client.post(f"{base}/element-types", json={"name": "Own type"}, headers=h).json()
    element = client.post(f"{base}/elements", json={"name": "Uses own", "element_type_id": own["id"]}, headers=h).json()
    assert client.delete(f"{base}/element-types/{own['id']}", headers=h).status_code == 409
    changed = put_element(client, token, project["id"], element, element_type_id=element_types(client, token, project["id"])["Sensor"])
    assert changed["element_type_name"] == "Sensor"
    assert client.delete(f"{base}/element-types/{own['id']}", headers=h).status_code == 204


def test_the_owner_may_be_a_member_or_a_group_and_is_validated(client, admin_token):
    org, project, token = setup(client, admin_token, "Arch element owner")
    h = auth_headers(token)
    user_id, _t = add_member(client, token, org["id"], project["id"], "owner.arch@example.com")
    other_org, other_token = create_org_admin_in(client, admin_token, "Arch element owner other")
    outsider = client.get("/api/v1/auth/me", headers=auth_headers(other_token)).json()["id"]
    group = client.post(f"/api/v1/projects/{project['id']}/groups", json={"name": "Platform team"}, headers=h).json()

    owned = make_element(client, token, project["id"], "Owned", owner={"type": "user", "id": user_id})
    assert owned["owner"]["id"] == user_id
    make_element(client, token, project["id"], "Outsider", owner={"type": "user", "id": outsider}, expect=400)
    made = put_element(client, token, project["id"], owned, owner={"type": "project_group", "id": group["id"]})
    assert made["owner"]["type"] == "project_group" and made["owner"]["label"] == "Platform team"
    cleared = put_element(client, token, project["id"], made, owner=None)
    assert cleared["owner"] is None
    assert other_org["id"] != org["id"]


def test_retiring_or_archiving_needs_the_children_finished_first(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch element retire")
    h = auth_headers(token)
    base = project_base(project["id"])
    parent = make_element(client, token, project["id"], "Parent", activate=True)
    child = make_element(client, token, project["id"], "Child", parent_id=parent["id"], activate=True)

    blocked = client.post(f"{base}/elements/{parent['id']}/status", json={"version": parent["version"], "status": "retired"}, headers=h)
    assert blocked.status_code == 409
    assert client.post(f"{base}/elements/{parent['id']}/archive", headers=h).status_code == 409

    retired_child = client.post(f"{base}/elements/{child['id']}/status", json={"version": child["version"], "status": "retired"}, headers=h)
    assert retired_child.status_code == 200 and retired_child.json()["status"] == "retired"
    parent_now = client.get(f"{base}/elements/{parent['id']}", headers=h).json()
    ok = client.post(f"{base}/elements/{parent['id']}/status", json={"version": parent_now["version"], "status": "retired"}, headers=h)
    assert ok.status_code == 200
    same = client.post(f"{base}/elements/{parent['id']}/status", json={"version": ok.json()["version"], "status": "retired"}, headers=h)
    assert same.status_code == 409
    reactivated = client.post(f"{base}/elements/{parent['id']}/status", json={"version": ok.json()["version"], "status": "active"}, headers=h)
    assert reactivated.status_code == 200 and reactivated.json()["status"] == "active"


def test_archiving_hides_an_element_from_the_default_list_and_it_can_be_restored(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch element archive")
    h = auth_headers(token)
    base = project_base(project["id"])
    element = make_element(client, token, project["id"], "To archive")
    archived = client.post(f"{base}/elements/{element['id']}/archive", headers=h)
    assert archived.status_code == 200 and archived.json()["is_archived"] is True
    assert client.get(f"{base}/elements", headers=h).json() == []
    assert len(client.get(f"{base}/elements", params={"include_archived": "true"}, headers=h).json()) == 1
    restored = client.post(f"{base}/elements/{element['id']}/unarchive", headers=h)
    assert restored.status_code == 200 and restored.json()["is_archived"] is False


def test_an_element_with_children_or_a_connection_is_not_deleted_and_a_free_one_is(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch element delete")
    h = auth_headers(token)
    base = project_base(project["id"])
    parent = make_element(client, token, project["id"], "Parent")
    child = make_element(client, token, project["id"], "Child", parent_id=parent["id"])
    other = make_element(client, token, project["id"], "Other")
    connection = make_connection(client, token, project["id"], child["id"], other["id"])

    assert client.delete(f"{base}/elements/{parent['id']}", headers=h).status_code == 409
    assert client.delete(f"{base}/elements/{child['id']}", headers=h).status_code == 409
    assert client.delete(f"{base}/connections/{connection['id']}", headers=h).status_code == 204
    assert client.delete(f"{base}/elements/{child['id']}", headers=h).status_code == 204
    assert client.delete(f"{base}/elements/{parent['id']}", headers=h).status_code == 204
    assert client.get(f"{base}/elements/{parent['id']}", headers=h).status_code == 404


def test_list_filters_narrow_the_elements(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch element filters")
    h = auth_headers(token)
    base = project_base(project["id"])
    types = element_types(client, token, project["id"])
    board = make_element(client, token, project["id"], "Main board", type_name="Board", activate=True, description="Holds the MCU.")
    sensor = make_element(client, token, project["id"], "Temperature sensor", type_name="Sensor", parent_id=board["id"])
    retired = make_element(client, token, project["id"], "Old radio", type_name="Board")
    client.post(f"{base}/elements/{retired['id']}/status", json={"version": 1, "status": "retired"}, headers=h)

    def ids(**params) -> set[str]:
        resp = client.get(f"{base}/elements", params=params, headers=h)
        assert resp.status_code == 200, resp.text
        return {e["id"] for e in resp.json()}

    assert ids(status="active") == {board["id"]}
    assert ids(element_type_id=types["Sensor"]) == {sensor["id"]}
    assert ids(roots_only="true") == {board["id"], retired["id"]}
    assert ids(open_only="true") == {board["id"], sensor["id"]}
    assert ids(search="mcu") == {board["id"]}
    assert ids(search="ELM-002") == {sensor["id"]}
    assert client.get(f"{base}/elements", params={"status": "bogus"}, headers=h).status_code == 422


def test_audit_events_hold_ids_and_field_names_never_free_text(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch element audit")
    element = make_element(client, token, project["id"], "Secret codename", description="Sensitive wording.", ports=[{"name": "Hidden port"}])
    put_element(client, token, project["id"], element, name="Another secret", description="More sensitive wording.")
    with SessionLocal() as db:
        events = list(db.scalars(select(AuditEvent).where(
            AuditEvent.entity_type == "architecture_element", AuditEvent.entity_id == element["id"],
        ).order_by(AuditEvent.created_at)))
    assert [e.action for e in events] == ["created", "updated"]
    text = " ".join(str(e.detail) for e in events)
    assert "secret" not in text.lower() and "sensitive" not in text.lower() and "Hidden port" not in text
    assert events[1].detail == {"fields": ["description", "name"]}


def test_another_projects_element_looks_absent(client, admin_token):
    org, project, token = setup(client, admin_token, "Arch element tenancy")
    other = create_project(client, token, org["id"], "Arch element tenancy other")
    element = make_element(client, token, other["id"], "Elsewhere")
    base = project_base(project["id"])
    h = auth_headers(token)
    assert client.get(f"{base}/elements/{element['id']}", headers=h).status_code == 404
    assert client.put(f"{base}/elements/{element['id']}", json={"version": 1, "name": "x"}, headers=h).status_code == 404
    assert client.delete(f"{base}/elements/{element['id']}", headers=h).status_code == 404
    assert client.post(f"{base}/elements/{element['id']}/archive", headers=h).status_code == 404

    with SessionLocal() as db:
        assert db.get(ArchitectureElement, uuid.UUID(element["id"])) is not None


def test_a_child_project_lists_the_parents_elements_only_when_the_scope_is_widened(client, admin_token):
    org, parent_project, token = setup(client, admin_token, "Arch element scope")
    h = auth_headers(token)
    assert client.patch(f"/api/v1/projects/{parent_project['id']}", json={"can_be_parent": True}, headers=h).status_code == 200
    child_project = create_project(client, token, org["id"], "Arch element scope child", parent_project_id=parent_project["id"])
    inherited = make_element(client, token, parent_project["id"], "From the parent")
    own = make_element(client, token, child_project["id"], "Own")
    base = project_base(child_project["id"])

    plain = client.get(f"{base}/elements", headers=h).json()
    assert [e["id"] for e in plain] == [own["id"]]
    widened = client.get(f"{base}/elements", params={"project_scope": "parents"}, headers=h).json()
    by_id = {e["id"]: e for e in widened}
    assert set(by_id) == {own["id"], inherited["id"]}
    assert by_id[inherited["id"]]["from_project_id"] == parent_project["id"] and by_id[own["id"]]["from_project_id"] is None
