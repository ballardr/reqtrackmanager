"""Tests for connections: creation and codes, the Architect gate, end and port validation, edits that move an end,
the version lock, status and archive rules, deletion with its links, the summary label and tenant isolation. Every
test builds its own organisation."""

from __future__ import annotations

import uuid

from app.database import SessionLocal
from app.modules.architecture.tests._helpers import (
    add_member,
    connection_types,
    make_architect,
    make_connection,
    make_element,
    project_base,
    setup,
)
from app.modules.registry import get_artefact_summaries_in_project
from tests.conftest import auth_headers, create_project


def _two(client, token, project_id):
    a = make_element(client, token, project_id, "Sensor node", ports=[{"name": "Out", "direction": "out"}, {"name": "Aux"}])
    b = make_element(client, token, project_id, "Gateway", ports=[{"name": "In", "direction": "in"}])
    return a, b


def _put(client, token, project_id, connection, expect=200, **fields):
    resp = client.put(
        f"{project_base(project_id)}/connections/{connection['id']}", json={"version": connection["version"], **fields},
        headers=auth_headers(token),
    )
    assert resp.status_code == expect, resp.text
    return resp.json()


def test_a_connection_joins_two_elements_and_is_numbered(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch connection create")
    a, b = _two(client, token, project["id"])
    made = make_connection(
        client, token, project["id"], a["id"], b["id"], name="Telemetry", protocol="MQTT 5", description="Sends readings.",
        source_port_id=a["ports"][0]["id"], target_port_id=b["ports"][0]["id"],
    )
    assert (made["unique_code"], made["status"], made["version"]) == ("CON-001", "draft", 1)
    assert (made["source_element_code"], made["target_element_name"]) == ("ELM-001", "Gateway")
    assert (made["source_port_name"], made["target_port_name"], made["connection_type_name"]) == ("Out", "In", "REST API")
    assert made["directional"] is True and made["protocol"] == "MQTT 5"
    second = make_connection(client, token, project["id"], b["id"], a["id"], activate=True, type_name="SPI")
    assert (second["unique_code"], second["status"], second["directional"]) == ("CON-002", "active", False)


def test_the_two_ends_must_differ_and_belong_to_the_project(client, admin_token):
    org, project, token = setup(client, admin_token, "Arch connection ends")
    other = create_project(client, token, org["id"], "Arch connection ends other")
    a, b = _two(client, token, project["id"])
    foreign = make_element(client, token, other["id"], "Foreign")
    make_connection(client, token, project["id"], a["id"], a["id"], expect=400)
    make_connection(client, token, project["id"], a["id"], foreign["id"], expect=400)
    make_connection(client, token, project["id"], str(uuid.uuid4()), b["id"], expect=400)


def test_a_port_must_belong_to_its_end_and_an_archived_end_is_refused(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch connection ports")
    h = auth_headers(token)
    a, b = _two(client, token, project["id"])
    make_connection(client, token, project["id"], a["id"], b["id"], source_port_id=b["ports"][0]["id"], expect=400)
    make_connection(client, token, project["id"], a["id"], b["id"], target_port_id=a["ports"][0]["id"], expect=400)
    client.post(f"{project_base(project['id'])}/elements/{b['id']}/archive", headers=h)
    make_connection(client, token, project["id"], a["id"], b["id"], expect=400)


def test_the_connection_type_must_be_one_the_project_offers_and_a_used_type_is_not_deleted(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch connection type")
    h = auth_headers(token)
    base = project_base(project["id"])
    a, b = _two(client, token, project["id"])
    resp = client.post(f"{base}/connections", json={
        "connection_type_id": str(uuid.uuid4()), "source_element_id": a["id"], "target_element_id": b["id"],
    }, headers=h)
    assert resp.status_code == 400
    own = client.post(f"{base}/connection-types", json={"name": "Own bus"}, headers=h).json()
    made = client.post(f"{base}/connections", json={
        "connection_type_id": own["id"], "source_element_id": a["id"], "target_element_id": b["id"],
    }, headers=h).json()
    assert client.delete(f"{base}/connection-types/{own['id']}", headers=h).status_code == 409
    assert client.delete(f"{base}/connections/{made['id']}", headers=h).status_code == 204
    assert client.delete(f"{base}/connection-types/{own['id']}", headers=h).status_code == 204


def test_a_connection_type_a_port_uses_is_not_deleted_either(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch connection port type")
    h = auth_headers(token)
    base = project_base(project["id"])
    own = client.post(f"{base}/connection-types", json={"name": "Port bus"}, headers=h).json()
    make_element(client, token, project["id"], "Holder", ports=[{"name": "P", "connection_type_id": own["id"]}])
    assert client.delete(f"{base}/connection-types/{own['id']}", headers=h).status_code == 409


def test_an_edit_can_move_an_end_and_a_changed_element_drops_the_old_port(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch connection edit")
    a, b = _two(client, token, project["id"])
    c = make_element(client, token, project["id"], "Third", ports=[{"name": "Only"}])
    made = make_connection(client, token, project["id"], a["id"], b["id"], source_port_id=a["ports"][0]["id"], protocol="v1")

    renamed = _put(client, token, project["id"], made, name="Renamed", protocol="v2")
    assert (renamed["name"], renamed["protocol"], renamed["version"]) == ("Renamed", "v2", 2)
    moved = _put(client, token, project["id"], renamed, target_element_id=c["id"], target_port_id=c["ports"][0]["id"])
    assert (moved["target_element_code"], moved["target_port_name"]) == ("ELM-003", "Only")
    switched = _put(client, token, project["id"], moved, source_element_id=b["id"])
    assert switched["source_element_code"] == "ELM-002" and switched["source_port_id"] is None
    cleared = _put(client, token, project["id"], switched, target_port_id=None)
    assert cleared["target_port_id"] is None
    _put(client, token, project["id"], cleared, expect=400, source_element_id=c["id"])  # both ends would be the third element
    _put(client, token, project["id"], cleared, expect=400, target_port_id=a["ports"][0]["id"])


def test_a_stale_version_is_refused(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch connection version")
    a, b = _two(client, token, project["id"])
    made = make_connection(client, token, project["id"], a["id"], b["id"])
    _put(client, token, project["id"], made, name="First")
    stale = _put(client, token, project["id"], made, expect=409, name="Second")
    assert "changed by someone else" in stale["detail"]


def test_status_archive_and_delete_rules(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch connection lifecycle")
    h = auth_headers(token)
    base = project_base(project["id"])
    a, b = _two(client, token, project["id"])
    made = make_connection(client, token, project["id"], a["id"], b["id"])

    active = client.post(f"{base}/connections/{made['id']}/status", json={"version": 1, "status": "active"}, headers=h)
    assert active.status_code == 200 and active.json()["status"] == "active"
    assert client.post(f"{base}/connections/{made['id']}/status", json={"version": 1, "status": "retired"}, headers=h).status_code == 409
    assert client.post(f"{base}/connections/{made['id']}/status", json={"version": 2, "status": "active"}, headers=h).status_code == 409

    assert client.post(f"{base}/connections/{made['id']}/archive", headers=h).json()["is_archived"] is True
    assert client.get(f"{base}/connections", headers=h).json() == []
    client.post(f"{base}/elements/{a['id']}/archive", headers=h)
    assert client.post(f"{base}/connections/{made['id']}/unarchive", headers=h).status_code == 409
    client.post(f"{base}/elements/{a['id']}/unarchive", headers=h)
    assert client.post(f"{base}/connections/{made['id']}/unarchive", headers=h).json()["is_archived"] is False
    assert client.delete(f"{base}/connections/{made['id']}", headers=h).status_code == 204
    assert client.get(f"{base}/connections/{made['id']}", headers=h).status_code == 404


def test_only_an_architect_changes_connections_and_any_member_reads_them(client, admin_token):
    org, project, admin = setup(client, admin_token, "Arch connection gate")
    _uid, member = add_member(client, admin, org["id"], project["id"], "plain.conn@example.com")
    architect = make_architect(client, admin, org["id"], project["id"], "architect.conn@example.com")
    a, b = _two(client, admin, project["id"])
    base = project_base(project["id"])
    body = {
        "connection_type_id": next(iter(connection_types(client, admin, project["id"]).values())),
        "source_element_id": a["id"], "target_element_id": b["id"],
    }
    assert client.post(f"{base}/connections", json=body, headers=auth_headers(member)).status_code == 403
    made = client.post(f"{base}/connections", json=body, headers=auth_headers(architect))
    assert made.status_code == 201
    assert client.get(f"{base}/connections", headers=auth_headers(member)).status_code == 200
    assert client.delete(f"{base}/connections/{made.json()['id']}", headers=auth_headers(member)).status_code == 403


def test_list_filters_and_the_element_filter_match_either_end(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch connection filters")
    h = auth_headers(token)
    base = project_base(project["id"])
    a, b = _two(client, token, project["id"])
    c = make_element(client, token, project["id"], "Third")
    first = make_connection(client, token, project["id"], a["id"], b["id"], name="Telemetry link", protocol="MQTT")
    second = make_connection(client, token, project["id"], b["id"], c["id"], type_name="SPI", activate=True)

    def ids(**params) -> set[str]:
        resp = client.get(f"{base}/connections", params=params, headers=h)
        assert resp.status_code == 200, resp.text
        return {x["id"] for x in resp.json()}

    assert ids(element_id=b["id"]) == {first["id"], second["id"]}
    assert ids(element_id=a["id"]) == {first["id"]}
    assert ids(connection_type_id=connection_types(client, token, project["id"])["SPI"]) == {second["id"]}
    assert ids(status="active") == {second["id"]}
    assert ids(search="mqtt") == {first["id"]}


def test_the_summary_label_names_the_ends_and_is_scoped_to_the_project(client, admin_token):
    org, project, token = setup(client, admin_token, "Arch connection summary")
    other = create_project(client, token, org["id"], "Arch connection summary other")
    a, b = _two(client, token, project["id"])
    named = make_connection(client, token, project["id"], a["id"], b["id"], name="Telemetry")
    unnamed = make_connection(client, token, project["id"], b["id"], a["id"])
    with SessionLocal() as db:
        found = get_artefact_summaries_in_project(
            db, uuid.UUID(project["id"]), "architecture_connection",
            [uuid.UUID(named["id"]), uuid.UUID(unnamed["id"])],
        )
        elsewhere = get_artefact_summaries_in_project(
            db, uuid.UUID(other["id"]), "architecture_connection", [uuid.UUID(named["id"])],
        )
        elements = get_artefact_summaries_in_project(db, uuid.UUID(project["id"]), "architecture_element", [uuid.UUID(a["id"])])
    assert found is not None and elements is not None
    labels = {s.label for s in found.values()}
    assert labels == {"CON-001 Telemetry (ELM-001 → ELM-002)", "CON-002 (ELM-002 → ELM-001)"}
    assert not elsewhere
    assert next(iter(elements.values())).label == "ELM-001 Sensor node"


def test_another_projects_connection_looks_absent(client, admin_token):
    org, project, token = setup(client, admin_token, "Arch connection tenancy")
    other = create_project(client, token, org["id"], "Arch connection tenancy other")
    a, b = _two(client, token, other["id"])
    made = make_connection(client, token, other["id"], a["id"], b["id"])
    base = project_base(project["id"])
    h = auth_headers(token)
    assert client.get(f"{base}/connections/{made['id']}", headers=h).status_code == 404
    assert client.put(f"{base}/connections/{made['id']}", json={"version": 1, "name": "x"}, headers=h).status_code == 404
    assert client.delete(f"{base}/connections/{made['id']}", headers=h).status_code == 404
