"""Tests for the soft guidance on connection types: the suggestions an element type names (seeded, on create and edit,
tiers, hidden types, deletion), a connection that ignores the guidance saves, inherited configuration, and the bundle
round trips. Every test builds its own organisation."""

from __future__ import annotations

import io
import json
import uuid
import zipfile

from sqlalchemy import event, select

from app.database import SessionLocal, engine
from app.modules.architecture.models import ArchitectureElementType
from app.modules.architecture.service import DEFAULT_ELEMENT_TYPE_SUGGESTIONS
from app.modules.architecture.tests._helpers import (
    connection_types,
    enable_module,
    make_connection,
    make_element,
    org_base,
    project_base,
    setup,
)
from tests.conftest import auth_headers, create_org_admin_in, create_project


def _rows(client, token, url) -> dict[str, dict]:
    resp = client.get(url, headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return {r["name"]: r for r in resp.json()}


def _post(client, token, url, expect=201, **body) -> dict:
    resp = client.post(url, json=body, headers=auth_headers(token))
    assert resp.status_code == expect, resp.text
    return resp.json()


def _patch(client, token, url, expect=200, **body) -> dict:
    resp = client.patch(url, json=body, headers=auth_headers(token))
    assert resp.status_code == expect, resp.text
    return resp.json()


def _names(connection_rows: dict[str, dict], ids: list[str]) -> list[str]:
    by_id = {r["id"]: r["name"] for r in connection_rows.values()}
    return sorted(by_id[i] for i in ids)


# --- The seeded suggestions -----------------------------------------------------


def test_a_new_organisation_suggests_connection_types_for_sensors_and_services(client, admin_token):
    org, project, token = setup(client, admin_token, "Arch guidance seed")
    connections = _rows(client, token, f"{org_base(org['id'])}/connection-types")
    elements = _rows(client, token, f"{org_base(org['id'])}/element-types")
    for name, row in elements.items():
        assert _names(connections, row["suggested_connection_type_ids"]) == sorted(DEFAULT_ELEMENT_TYPE_SUGGESTIONS.get(name, ()))
    assert _names(connections, elements["Sensor"]["suggested_connection_type_ids"]) == ["Analogue signal", "I2C", "SPI", "UART"]
    # The project lists the same rows, so its picker can use them.
    project_elements = _rows(client, token, f"{project_base(project['id'])}/element-types")
    assert project_elements["Service"]["suggested_connection_type_ids"] == elements["Service"]["suggested_connection_type_ids"]


# --- Create and edit ------------------------------------------------------------


def test_suggestions_are_set_replaced_kept_and_cleared(client, admin_token):
    org, _project, token = setup(client, admin_token, "Arch guidance edit")
    connections = _rows(client, token, f"{org_base(org['id'])}/connection-types")
    base = f"{org_base(org['id'])}/element-types"
    i2c, spi, power = connections["I2C"]["id"], connections["SPI"]["id"], connections["Power"]["id"]

    created = _post(client, token, base, name="Radio", domain="hardware", suggested_connection_type_ids=[i2c, spi, i2c])
    assert sorted(created["suggested_connection_type_ids"]) == sorted([i2c, spi])  # a repeat counts once

    renamed = _patch(client, token, f"{base}/{created['id']}", name="Radio module")
    assert sorted(renamed["suggested_connection_type_ids"]) == sorted([i2c, spi])  # omitted: kept
    replaced = _patch(client, token, f"{base}/{created['id']}", suggested_connection_type_ids=[power])
    assert replaced["suggested_connection_type_ids"] == [power]
    cleared = _patch(client, token, f"{base}/{created['id']}", suggested_connection_type_ids=[])
    assert cleared["suggested_connection_type_ids"] == []
    assert _rows(client, token, base)["Radio module"]["suggested_connection_type_ids"] == []


def test_a_group_can_be_suggested_as_well_as_a_leaf(client, admin_token):
    org, _project, token = setup(client, admin_token, "Arch guidance group")
    connections = _rows(client, token, f"{org_base(org['id'])}/connection-types")
    made = _post(
        client, token, f"{org_base(org['id'])}/element-types", name="Bridge",
        suggested_connection_type_ids=[connections["Serial bus"]["id"]],
    )
    assert made["suggested_connection_type_ids"] == [connections["Serial bus"]["id"]]


def test_a_suggestion_must_be_a_connection_type_the_owner_can_use(client, admin_token):
    org, project, token = setup(client, admin_token, "Arch guidance tiers")
    other_org, other_token = create_org_admin_in(client, admin_token, "Arch guidance tiers other")
    enable_module(client, other_token, other_org["id"])
    foreign = _rows(client, other_token, f"{org_base(other_org['id'])}/connection-types")["Serial bus"]["id"]
    org_url, project_url = org_base(org["id"]), project_base(project["id"])
    serial = _rows(client, token, f"{org_url}/connection-types")["Serial bus"]["id"]
    mine = _post(client, token, f"{project_url}/connection-types", name="Project bus")

    _post(client, token, f"{org_url}/element-types", expect=400, name="Leaks", suggested_connection_type_ids=[foreign])
    _post(client, token, f"{org_url}/element-types", expect=400, name="Unknown", suggested_connection_type_ids=[str(uuid.uuid4())])
    _post(client, token, f"{project_url}/element-types", expect=400, name="Foreign", suggested_connection_type_ids=[foreign])
    # A project type may suggest an organisation default or its own type; an organisation type never a project's.
    made = _post(client, token, f"{project_url}/element-types", name="Local part", suggested_connection_type_ids=[serial, mine["id"]])
    assert sorted(made["suggested_connection_type_ids"]) == sorted([serial, mine["id"]])
    org_part = _post(client, token, f"{org_url}/element-types", name="Org part")
    _patch(client, token, f"{org_url}/element-types/{org_part['id']}", expect=400, suggested_connection_type_ids=[mine["id"]])


def test_a_hidden_connection_type_cannot_be_chosen_but_a_suggestion_already_made_is_kept(client, admin_token):
    org, project, token = setup(client, admin_token, "Arch guidance hidden")
    project_url = project_base(project["id"])
    serial = _rows(client, token, f"{org_base(org['id'])}/connection-types")["Serial bus"]["id"]
    mine = _post(client, token, f"{project_url}/element-types", name="Local part", suggested_connection_type_ids=[serial])

    assert client.delete(f"{project_url}/connection-types/{serial}", headers=auth_headers(token)).status_code == 204  # hides it
    _post(client, token, f"{project_url}/element-types", expect=400, name="Another", suggested_connection_type_ids=[serial])
    renamed = _patch(client, token, f"{project_url}/element-types/{mine['id']}", name="Local part 2", suggested_connection_type_ids=[serial])
    assert renamed["suggested_connection_type_ids"] == [serial]


# --- Guidance only ---------------------------------------------------------------


def test_a_connection_that_ignores_the_guidance_saves(client, admin_token):
    """A hardware sensor joined by a software-only type, and a type nobody suggested: both are stored as chosen."""
    _org, project, token = setup(client, admin_token, "Arch guidance soft")
    pid = project["id"]
    a, b = make_element(client, token, pid, "Sensor A", type_name="Sensor"), make_element(client, token, pid, "Sensor B", type_name="Sensor")
    mismatched = make_connection(client, token, pid, a["id"], b["id"], type_name="REST API")
    unsuggested = make_connection(client, token, pid, a["id"], b["id"], type_name="Power")
    assert mismatched["connection_type_name"] == "REST API" and unsuggested["connection_type_name"] == "Power"


# --- Deletion ---------------------------------------------------------------------


def test_deleting_a_connection_type_removes_it_from_the_suggestions(client, admin_token):
    org, _project, token = setup(client, admin_token, "Arch guidance delete")
    base = org_base(org["id"])
    extra = _post(client, token, f"{base}/connection-types", name="Extra bus")
    part = _post(client, token, f"{base}/element-types", name="Part", suggested_connection_type_ids=[extra["id"]])
    assert client.delete(f"{base}/connection-types/{extra['id']}", headers=auth_headers(token)).status_code == 204
    assert _rows(client, token, f"{base}/element-types")["Part"]["suggested_connection_type_ids"] == []
    assert part["id"] in {r["id"] for r in _rows(client, token, f"{base}/element-types").values()}


def test_deleting_an_element_type_removes_its_suggestions_and_keeps_the_connection_type(client, admin_token):
    org, _project, token = setup(client, admin_token, "Arch guidance delete element")
    base = org_base(org["id"])
    extra = _post(client, token, f"{base}/connection-types", name="Extra bus")
    part = _post(client, token, f"{base}/element-types", name="Part", suggested_connection_type_ids=[extra["id"]])
    assert client.delete(f"{base}/element-types/{part['id']}", headers=auth_headers(token)).status_code == 204
    assert "Extra bus" in _rows(client, token, f"{base}/connection-types")


# --- Inherited configuration -------------------------------------------------------


def test_a_child_project_keeps_the_suggestions_when_it_copies_an_inherited_configuration(client, admin_token):
    org, token = create_org_admin_in(client, admin_token, "Arch guidance inherit")
    enable_module(client, token, org["id"])
    parent = create_project(client, token, org["id"], "Arch guidance parent", can_be_parent=True)
    parent_url = project_base(parent["id"])
    serial = _rows(client, token, f"{parent_url}/connection-types")["Serial bus"]["id"]
    own_connection = _post(client, token, f"{parent_url}/connection-types", name="Parent bus")
    _post(client, token, f"{parent_url}/element-types", name="Parent part", suggested_connection_type_ids=[serial, own_connection["id"]])
    child = create_project(client, token, org["id"], "Arch guidance child", parent_project_id=parent["id"])
    child_url = project_base(child["id"])
    inherited = _rows(client, token, f"{child_url}/element-types")["Parent part"]
    assert sorted(inherited["suggested_connection_type_ids"]) == sorted([serial, own_connection["id"]])  # inherited, not copied

    # A change to the child's element types copies the configuration; the copies suggest the same connection types.
    _post(client, token, f"{child_url}/element-types", name="Child only")
    copy = _rows(client, token, f"{child_url}/element-types")["Parent part"]
    assert copy["id"] != inherited["id"] and copy["project_id"] == child["id"]
    assert sorted(copy["suggested_connection_type_ids"]) == sorted([serial, own_connection["id"]])
    assert _rows(client, token, f"{parent_url}/element-types")["Parent part"]["id"] == inherited["id"]  # the ancestor is untouched

    # A later change to the child's connection types copies those too; its own element types then name the copies.
    _post(client, token, f"{child_url}/connection-types", name="Child bus")
    copies = _rows(client, token, f"{child_url}/connection-types")
    assert copies["Parent bus"]["id"] != own_connection["id"]
    remapped = _rows(client, token, f"{child_url}/element-types")["Parent part"]
    assert sorted(remapped["suggested_connection_type_ids"]) == sorted([serial, copies["Parent bus"]["id"]])


# --- Bundles ---------------------------------------------------------------------


def test_the_suggestions_survive_an_organisation_bundle(client, admin_token):
    org, _project, token = setup(client, admin_token, "Arch guidance org bundle")
    h = auth_headers(token)
    base = org_base(org["id"])
    connections = _rows(client, token, f"{base}/connection-types")
    _post(client, token, f"{base}/element-types", name="Radio", suggested_connection_type_ids=[connections["UART"]["id"]])

    export = client.get(f"/api/v1/orgs/{org['id']}/export", headers=h)
    assert export.status_code == 200, export.text
    entries = json.loads(zipfile.ZipFile(io.BytesIO(export.content)).read("org.json"))["architecture_element_types"]
    assert next(e for e in entries if e["name"] == "Radio")["suggested_names"] == ["UART"]
    assert next(e for e in entries if e["name"] == "Service")["suggested_names"] == ["Message queue", "REST API", "gRPC"]

    imported = client.post(
        "/api/v1/orgs/import", data={"name": "Arch guidance org bundle copy"},
        files={"file": ("bundle.zip", export.content, "application/zip")}, headers=auth_headers(admin_token),
    )
    assert imported.status_code == 201, imported.text
    new_org = uuid.UUID(imported.json()["organization"]["id"])
    with SessionLocal() as db:
        from app.modules.architecture.models import ArchitectureConnectionType

        names = {r.id: r.name for r in db.scalars(select(ArchitectureConnectionType).where(ArchitectureConnectionType.organization_id == new_org))}
        rows = {r.name: r for r in db.scalars(select(ArchitectureElementType).where(ArchitectureElementType.organization_id == new_org))}
        assert [names[c] for c in rows["Radio"].suggested_connection_type_ids] == ["UART"]
        assert sorted(names[c] for c in rows["Sensor"].suggested_connection_type_ids) == ["Analogue signal", "I2C", "SPI", "UART"]  # not doubled


def test_a_project_bundle_carries_the_suggestions_and_reports_a_type_the_target_lacks(client, admin_token):
    org, project, token = setup(client, admin_token, "Arch guidance project bundle")
    h = auth_headers(token)
    base = project_base(project["id"])
    serial = _rows(client, token, f"{base}/connection-types")["Serial bus"]["id"]
    local = _post(client, token, f"{base}/connection-types", name="Local bus")
    _post(client, token, f"{base}/element-types", name="Local part", suggested_connection_type_ids=[serial, local["id"]])

    export = client.get(f"/api/v1/projects/{project['id']}/export", headers=h)
    assert export.status_code == 200, export.text
    entries = json.loads(zipfile.ZipFile(io.BytesIO(export.content)).read("project.json"))["architecture_project_element_types"]
    assert next(e for e in entries if e["name"] == "Local part")["suggested_names"] == ["Local bus", "Serial bus"]

    imported = client.post(
        "/api/v1/projects/import", data={"organization_id": org["id"], "name": "Arch guidance project copy"},
        files={"file": ("bundle.zip", export.content, "application/zip")}, headers=h,
    )
    assert imported.status_code == 201, imported.text
    copy_base = project_base(imported.json()["project"]["id"])
    copy_connections = _rows(client, token, f"{copy_base}/connection-types")
    part = _rows(client, token, f"{copy_base}/element-types")["Local part"]
    assert _names(copy_connections, part["suggested_connection_type_ids"]) == ["Local bus", "Serial bus"]

    # The organisation drops the group before a second import: the suggestion is reported, not guessed.
    assert client.delete(f"{org_base(org['id'])}/connection-types/{serial}", headers=h).status_code == 204
    again = client.post(
        "/api/v1/projects/import", data={"organization_id": org["id"], "name": "Arch guidance project copy 2"},
        files={"file": ("bundle.zip", export.content, "application/zip")}, headers=h,
    )
    assert again.status_code == 201, again.text
    assert any("Serial bus" in w for w in again.json().get("warnings", []))
    second = _rows(client, token, f"{project_base(again.json()['project']['id'])}/element-types")["Local part"]
    assert len(second["suggested_connection_type_ids"]) == 1


# --- Cost ------------------------------------------------------------------------


def test_listing_the_element_types_costs_the_same_however_many_suggest_types(client, admin_token):
    org, _project, token = setup(client, admin_token, "Arch guidance statements")
    base = f"{org_base(org['id'])}/element-types"
    serial = _rows(client, token, f"{org_base(org['id'])}/connection-types")["Serial bus"]["id"]
    statements: list[str] = []

    def record(conn, cursor, statement, *rest):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        client.get(base, headers=auth_headers(token))
        small = len(statements)
        for i in range(12):
            _post(client, token, base, name=f"Extra {i}", suggested_connection_type_ids=[serial])
        statements.clear()
        client.get(base, headers=auth_headers(token))
        large = len(statements)
    finally:
        event.remove(engine, "before_cursor_execute", record)
    assert large == small


def test_connection_types_helper_is_unchanged_by_suggestions(client, admin_token):
    """The picker's source list is still every effective type; suggestions only order it."""
    _org, project, token = setup(client, admin_token, "Arch guidance picker")
    assert {"I2C", "Serial bus", "REST API"} <= set(connection_types(client, token, project["id"]))
