"""Tests for a connection type's default protocol: it pre-fills a new connection (only when the request leaves the protocol
out), is never applied to a connection that exists, travels through the vocabulary tiers, the nested-project copy and both
bundles, and a rolled-up line shows the protocol its connections share. Every test builds its own organisation."""

from __future__ import annotations

import io
import json
import uuid
import zipfile

from sqlalchemy import select

from app.database import SessionLocal
from app.modules.architecture.models import ArchitectureConnectionType
from app.modules.architecture.tests._helpers import (
    make_connection,
    make_diagram,
    make_element,
    org_base,
    place_all,
    project_base,
    setup,
    view,
)
from tests.conftest import auth_headers, create_project


def _type(client, token, base, **fields) -> dict:
    resp = client.post(f"{base}/connection-types", json={"name": "Sensor bus", **fields}, headers=auth_headers(token))
    assert resp.status_code == 201, resp.text
    return resp.json()


def _pair(client, token, p):
    return make_element(client, token, p, "Alpha"), make_element(client, token, p, "Bravo")


def test_a_type_stores_a_trimmed_default_protocol_and_an_empty_string_clears_it(client, admin_token):
    org, project, token = setup(client, admin_token, "Arch proto types")
    h = auth_headers(token)
    row = _type(client, token, org_base(org["id"]), default_protocol="  SPI mode 0  ")
    assert row["default_protocol"] == "SPI mode 0"
    assert _type(client, token, org_base(org["id"]), name="Plain")["default_protocol"] == ""
    base = f"{org_base(org['id'])}/connection-types/{row['id']}"
    assert client.patch(base, json={"name": "Renamed"}, headers=h).json()["default_protocol"] == "SPI mode 0"  # left out is kept
    assert client.patch(base, json={"default_protocol": "UART 9600"}, headers=h).json()["default_protocol"] == "UART 9600"
    assert client.patch(base, json={"default_protocol": ""}, headers=h).json()["default_protocol"] == ""
    assert client.patch(base, json={"default_protocol": "x" * 201}, headers=h).status_code == 422
    project_row = _type(client, token, project_base(project["id"]), name="Local", default_protocol="CAN 500k")
    assert project_row["default_protocol"] == "CAN 500k" and project_row["project_id"] == project["id"]


def test_a_new_connection_takes_the_types_default_only_when_the_protocol_is_left_out(client, admin_token):
    org, project, token = setup(client, admin_token, "Arch proto create")
    p = project["id"]
    _type(client, token, org_base(org["id"]), default_protocol="SPI mode 0")
    a, b = _pair(client, token, p)
    left_out = make_connection(client, token, p, a["id"], b["id"], type_name="Sensor bus")
    given = make_connection(client, token, p, a["id"], b["id"], type_name="Sensor bus", protocol="SPI mode 3")
    empty = make_connection(client, token, p, a["id"], b["id"], type_name="Sensor bus", protocol="")
    padded = make_connection(client, token, p, a["id"], b["id"], type_name="Sensor bus", protocol="  ")
    assert (left_out["protocol"], given["protocol"], empty["protocol"], padded["protocol"]) == ("SPI mode 0", "SPI mode 3", "", "")
    assert make_connection(client, token, p, a["id"], b["id"], type_name="REST API")["protocol"] == ""  # no default, none


def test_changing_the_default_or_the_type_leaves_existing_connections_alone(client, admin_token):
    org, project, token = setup(client, admin_token, "Arch proto update")
    p, h = project["id"], auth_headers(token)
    kind = _type(client, token, org_base(org["id"]), default_protocol="SPI mode 0")
    a, b = _pair(client, token, p)
    connection = make_connection(client, token, p, a["id"], b["id"], type_name="Sensor bus")
    client.patch(f"{org_base(org['id'])}/connection-types/{kind['id']}", json={"default_protocol": "SPI mode 3"}, headers=h)
    url = f"{project_base(p)}/connections/{connection['id']}"
    assert client.get(url, headers=h).json()["protocol"] == "SPI mode 0"  # no backfill
    other = _type(client, token, org_base(org["id"]), name="Other bus", default_protocol="I2C 400k")
    moved = client.put(url, json={"version": connection["version"], "connection_type_id": other["id"]}, headers=h)
    assert moved.status_code == 200 and moved.json()["protocol"] == "SPI mode 0"  # an update never applies a default
    cleared = client.put(url, json={"version": moved.json()["version"], "protocol": ""}, headers=h)
    assert cleared.json()["protocol"] == ""  # and a person can still empty it


def test_a_child_project_inherits_a_default_and_copies_it_with_its_first_change(client, admin_token):
    org, _project, token = setup(client, admin_token, "Arch proto nested")
    h = auth_headers(token)
    parent = create_project(client, token, org["id"], "Arch proto nested parent", can_be_parent=True)
    _type(client, token, project_base(parent["id"]), default_protocol="SPI mode 0")
    child = create_project(client, token, org["id"], "Arch proto nested child", parent_project_id=parent["id"])
    cb = project_base(child["id"])
    assert next(r for r in client.get(f"{cb}/connection-types", headers=h).json() if r["name"] == "Sensor bus")["default_protocol"] == "SPI mode 0"
    _type(client, token, cb, name="Child only")  # the first change copies the inherited rows into the child
    copy = next(r for r in client.get(f"{cb}/connection-types", headers=h).json() if r["name"] == "Sensor bus")
    assert copy["project_id"] == child["id"] and copy["default_protocol"] == "SPI mode 0"
    a, b = _pair(client, token, child["id"])
    assert make_connection(client, token, child["id"], a["id"], b["id"], type_name="Sensor bus")["protocol"] == "SPI mode 0"


def test_the_default_round_trips_through_both_bundles_and_an_older_bundle_reads_empty(client, admin_token):
    org, project, token = setup(client, admin_token, "Arch proto bundles")
    h = auth_headers(token)
    _type(client, token, org_base(org["id"]), default_protocol="SPI mode 0")
    _type(client, token, project_base(project["id"]), name="Local bus", default_protocol="CAN 500k")

    org_zip = client.get(f"/api/v1/orgs/{org['id']}/export", headers=h).content
    org_json = json.loads(zipfile.ZipFile(io.BytesIO(org_zip)).read("org.json"))
    exported = next(t for t in org_json["architecture_connection_types"] if t["name"] == "Sensor bus")
    assert exported["default_protocol"] == "SPI mode 0"
    imported = client.post(
        "/api/v1/orgs/import", data={"name": "Arch proto bundles org copy"}, files={"file": ("b.zip", org_zip, "application/zip")},
        headers=auth_headers(admin_token),
    )
    assert imported.status_code == 201, imported.text
    with SessionLocal() as db:
        rows = list(db.scalars(select(ArchitectureConnectionType).where(
            ArchitectureConnectionType.organization_id == uuid.UUID(imported.json()["organization"]["id"]),
        )))
    assert {r.name: r.default_protocol for r in rows}["Sensor bus"] == "SPI mode 0"
    assert {r.name: r.default_protocol for r in rows}["REST API"] == ""

    project_zip = client.get(f"/api/v1/projects/{project['id']}/export", headers=h).content
    project_json = json.loads(zipfile.ZipFile(io.BytesIO(project_zip)).read("project.json"))
    assert project_json["architecture_project_connection_types"][0]["default_protocol"] == "CAN 500k"
    copy = client.post(
        "/api/v1/projects/import", data={"organization_id": org["id"], "name": "Arch proto bundles project copy"},
        files={"file": ("b.zip", project_zip, "application/zip")}, headers=h,
    )
    assert copy.status_code == 201, copy.text
    types = client.get(f"{project_base(copy.json()['project']['id'])}/connection-types", headers=h).json()
    assert next(r for r in types if r["name"] == "Local bus")["default_protocol"] == "CAN 500k"

    # A bundle written before the field existed has no key: the type imports with no default.
    del project_json["architecture_project_connection_types"][0]["default_protocol"]
    older = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(project_zip)) as source, zipfile.ZipFile(older, "w") as target:
        for item in source.infolist():
            target.writestr(item, json.dumps(project_json) if item.filename == "project.json" else source.read(item.filename))
    again = client.post(
        "/api/v1/projects/import", data={"organization_id": org["id"], "name": "Arch proto bundles older"},
        files={"file": ("b.zip", older.getvalue(), "application/zip")}, headers=h,
    )
    assert again.status_code == 201, again.text
    types = client.get(f"{project_base(again.json()['project']['id'])}/connection-types", headers=h).json()
    assert next(r for r in types if r["name"] == "Local bus")["default_protocol"] == ""


def _rolled_up(client, token, p, protocols):
    """A diagram of two systems, each holding a part that connects to the same far element with the given protocols."""
    platform = make_element(client, token, p, "Platform", type_name="System")
    cloud = make_element(client, token, p, "Cloud", type_name="System")
    for i, protocol in enumerate(protocols):
        part = make_element(client, token, p, f"Part {i}", parent_id=platform["id"])
        make_connection(client, token, p, part["id"], cloud["id"], protocol=protocol)
    diagram = place_all(client, token, p, make_diagram(client, token, p, "Context", connection_detail=True), platform["id"], cloud["id"])
    return view(client, token, p, diagram["id"])["edges"]


def test_a_merged_line_shows_the_protocol_its_connections_share_and_none_when_they_differ(client, admin_token):
    for name, protocols, label in (
        ("shared", ["HTTPS", "HTTPS"], "REST API ×2 · HTTPS"),
        ("mixed", ["HTTPS", "HTTP"], "REST API ×2"),
        ("blank", ["HTTPS", ""], "REST API ×2"),
    ):
        _org, project, token = setup(client, admin_token, f"Arch proto merged {name}")
        (edge,) = _rolled_up(client, token, project["id"], protocols)
        assert edge["rolled_up"] and edge["label"] == label, name
