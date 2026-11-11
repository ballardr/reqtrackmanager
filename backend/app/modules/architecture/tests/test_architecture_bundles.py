"""Tests for the Architecture bundle sections (`export.py`): an organisation's default types survive
`GET /orgs/{id}/export` + `POST /orgs/import` without doubling the seeded defaults, and a project's own types and
hidden defaults survive `GET /projects/{id}/export` + `POST /projects/import`. Every test builds its own organisation."""

from __future__ import annotations

import io
import json
import uuid
import zipfile

from sqlalchemy import select

from app.database import SessionLocal
from app.modules.architecture.models import ArchitectureConnectionType, ArchitectureElementType
from app.modules.architecture.tests._helpers import org_base, project_base, setup
from tests.conftest import auth_headers


def _names(client, url, token) -> list[str]:
    resp = client.get(url, headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return [r["name"] for r in resp.json()]


def test_organisation_defaults_round_trip_without_doubling_the_seeds(client, admin_token):
    org, _project, token = setup(client, admin_token, "Arch bundle org")
    h = auth_headers(token)
    client.post(f"{org_base(org['id'])}/element-types", json={"name": "Radar", "shape": "ellipse", "domain": "hardware"}, headers=h)
    client.post(f"{org_base(org['id'])}/connection-types", json={"name": "LIN", "directional": False}, headers=h)

    export = client.get(f"/api/v1/orgs/{org['id']}/export", headers=h)
    assert export.status_code == 200, export.text
    org_json = json.loads(zipfile.ZipFile(io.BytesIO(export.content)).read("org.json"))
    assert "Radar" in [t["name"] for t in org_json["architecture_element_types"]]
    assert "id" not in org_json["architecture_element_types"][0] and "organization_id" not in org_json["architecture_element_types"][0]

    imported = client.post(
        "/api/v1/orgs/import", data={"name": "Arch bundle org reimport"},
        files={"file": ("bundle.zip", export.content, "application/zip")}, headers=auth_headers(admin_token),
    )
    assert imported.status_code == 201, imported.text
    new_org_id = uuid.UUID(imported.json()["organization"]["id"])
    with SessionLocal() as db:
        elements = list(db.scalars(select(ArchitectureElementType).where(ArchitectureElementType.organization_id == new_org_id)))
        connections = list(db.scalars(select(ArchitectureConnectionType).where(ArchitectureConnectionType.organization_id == new_org_id)))
    assert len({e.name for e in elements}) == len(elements) and {"Radar", "System"} <= {e.name for e in elements}
    radar = next(e for e in elements if e.name == "Radar")
    assert (radar.shape, radar.domain) == ("ellipse", "hardware")
    lin = next(c for c in connections if c.name == "LIN")
    assert lin.directional is False and len({c.name for c in connections}) == len(connections)


def test_project_types_and_hidden_defaults_round_trip(client, admin_token):
    org, project, token = setup(client, admin_token, "Arch bundle project")
    h = auth_headers(token)
    base = project_base(project["id"])
    client.post(f"{base}/element-types", json={"name": "Local block", "shape": "chip", "color_dark": "#010203"}, headers=h)
    client.post(f"{base}/connection-types", json={"name": "Local bus", "line_style": "dotted"}, headers=h)
    first = client.get(f"{base}/element-types", headers=h).json()[0]
    client.delete(f"{base}/element-types/{first['id']}", headers=h)

    export = client.get(f"/api/v1/projects/{project['id']}/export", headers=h)
    assert export.status_code == 200, export.text
    project_json = json.loads(zipfile.ZipFile(io.BytesIO(export.content)).read("project.json"))
    assert [t["name"] for t in project_json["architecture_project_element_types"]] == ["Local block"]
    assert project_json["architecture_hidden_element_types"] == [first["name"]]

    imported = client.post(
        "/api/v1/projects/import", data={"organization_id": org["id"], "name": "Arch bundle project copy"},
        files={"file": ("bundle.zip", export.content, "application/zip")}, headers=h,
    )
    assert imported.status_code == 201, imported.text
    copy_id = imported.json()["project"]["id"]
    copy_base = project_base(copy_id)
    names = _names(client, f"{copy_base}/element-types", token)
    assert "Local block" in names and first["name"] not in names
    rows = client.get(f"{copy_base}/element-types", headers=h).json()
    local = next(r for r in rows if r["name"] == "Local block")
    assert (local["shape"], local["color_dark"], local["project_id"]) == ("chip", "#010203", copy_id)
    connection = next(r for r in client.get(f"{copy_base}/connection-types", headers=h).json() if r["name"] == "Local bus")
    assert connection["line_style"] == "dotted"


def test_a_hidden_default_the_target_organisation_lacks_is_reported_not_guessed(client, admin_token):
    org, project, token = setup(client, admin_token, "Arch bundle lacking")
    h = auth_headers(token)
    first = client.get(f"{project_base(project['id'])}/connection-types", headers=h).json()[0]
    client.delete(f"{project_base(project['id'])}/connection-types/{first['id']}", headers=h)
    export = client.get(f"/api/v1/projects/{project['id']}/export", headers=h)
    # The organisation drops that default before the import.
    client.delete(f"{org_base(org['id'])}/connection-types/{first['id']}", headers=h)

    imported = client.post(
        "/api/v1/projects/import", data={"organization_id": org["id"], "name": "Arch bundle lacking copy"},
        files={"file": ("bundle.zip", export.content, "application/zip")}, headers=h,
    )
    assert imported.status_code == 201, imported.text
    assert any(first["name"] in warning for warning in imported.json().get("warnings", []))
    assert first["name"] not in _names(client, f"{project_base(imported.json()['project']['id'])}/connection-types", token)
