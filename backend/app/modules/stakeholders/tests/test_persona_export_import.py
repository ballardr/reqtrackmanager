"""Tests for Persona bundle export/import (`export.py`): a project's personas,
type rows, attachments and weight overrides survive `GET /projects/{id}/export`
+ `POST /projects/import`, and an organisation's types and org personas
survive `GET /orgs/{id}/export` + `POST /orgs/import`. Version history and
comments deliberately don't travel (see `export.py`)."""

from __future__ import annotations

import io
import json
import uuid
import zipfile

from sqlalchemy import select

from app.database import SessionLocal
from app.modules.stakeholders.enums import PersonaStatus
from app.modules.stakeholders.models import Persona, PersonaTypeDefinition
from app.modules.stakeholders.service import get_current_persona_version
from app.modules.stakeholders.tests.test_persona_api import (
    _PAYLOAD,
    _create_org_persona,
    _create_project_persona,
    _project_base,
    _setup,
)
from tests.conftest import auth_headers


def test_project_export_import_round_trips_personas(client, admin_token):
    org, project, token = _setup(client, admin_token, "Persona Bundle Project Co")
    h = auth_headers(token)
    base = _project_base(project["id"])

    types = client.get(base + "/persona-types", headers=h).json()
    client.put(f"{base}/persona-types/{types[0]['id']}", json={"name": "Core user"}, headers=h)
    local = client.post(base + "/persona-types", json={"name": "Project-only"}, headers=h).json()
    org_persona = _create_org_persona(client, token, org["id"], name="Shared persona", weight=1.5)

    typed = _create_project_persona(client, token, project["id"], name="Typed", persona_type_id=local["id"], weight=2.0)
    client.post(f"{base}/personas/{typed['id']}/activate", headers=h)
    client.post(
        f"{base}/personas/{typed['id']}/files", files={"file": ("brief.txt", b"persona brief", "text/plain")}, headers=h,
    )
    client.put(f"{base}/personas/{typed['id']}/weight", json={"weight": 7.0}, headers=h)
    client.put(f"{base}/personas/{org_persona['id']}/weight", json={"weight": 9.0}, headers=h)

    export = client.get(f"/api/v1/projects/{project['id']}/export", headers=h)
    assert export.status_code == 200
    exported = json.loads(zipfile.ZipFile(io.BytesIO(export.content)).read("project.json"))
    assert [p["name"] for p in exported["project_personas"]] == ["Typed"]

    imported = client.post(
        "/api/v1/projects/import", data={"organization_id": org["id"], "name": "Persona Bundle Reimported"},
        files={"file": ("bundle.zip", export.content, "application/zip")}, headers=h,
    )
    assert imported.status_code == 201, imported.text
    assert imported.json()["warnings"] == []
    new_project = imported.json()["project"]
    new_base = _project_base(new_project["id"])

    personas = client.get(new_base + "/personas?include_org=false", headers=h).json()
    assert len(personas) == 1
    persona = personas[0]
    assert persona["name"] == "Typed" and persona["status"] == "active"
    assert persona["persona_type_name"] == "Project-only"
    assert persona["goals"] == _PAYLOAD["goals"]
    assert persona["weight"] == 2.0 and persona["weight_override"] == 7.0

    org_view = client.get(f"{new_base}/personas/{org_persona['id']}", headers=h).json()
    assert org_view["weight_override"] == 9.0  # the override on a shared org persona is carried by name

    effective = {t["name"] for t in client.get(new_base + "/persona-types", headers=h).json()}
    assert {"Core user", "Project-only"} <= effective

    files = client.get(f"{new_base}/personas/{persona['id']}/files", headers=h).json()
    assert [f["filename"] for f in files] == ["brief.txt"]


def test_project_import_into_org_lacking_org_persona_warns_and_skips_override(client, admin_token):
    org, project, token = _setup(client, admin_token, "Persona Bundle Warn Co")
    h = auth_headers(token)
    org_persona = _create_org_persona(client, token, org["id"], name="Only here")
    client.put(f"{_project_base(project['id'])}/personas/{org_persona['id']}/weight", json={"weight": 3}, headers=h)
    export = client.get(f"/api/v1/projects/{project['id']}/export", headers=h)

    other, other_token = _setup(client, admin_token, "Persona Bundle Warn Target Co")[::2]
    imported = client.post(
        "/api/v1/projects/import", data={"organization_id": other["id"], "name": "Warn Target Reimport"},
        files={"file": ("bundle.zip", export.content, "application/zip")}, headers=auth_headers(other_token),
    )
    assert imported.status_code == 201, imported.text
    assert any("weight override was skipped" in w for w in imported.json()["warnings"])


def test_org_export_import_round_trips_types_and_org_personas(client, admin_token):
    org, project, token = _setup(client, admin_token, "Persona Bundle Org Co")
    h = auth_headers(token)
    created = client.post(f"/api/v1/orgs/{org['id']}/modules/stakeholders/persona-types", json={"name": "Edge case"}, headers=h)
    assert created.status_code == 201, created.text
    persona = _create_org_persona(client, token, org["id"], name="Org shared", persona_type_id=created.json()["id"], weight=4.0)
    client.post(f"/api/v1/orgs/{org['id']}/modules/stakeholders/personas/{persona['id']}/retire", headers=h)

    export = client.get(f"/api/v1/orgs/{org['id']}/export", headers=h)
    assert export.status_code == 200
    org_json = json.loads(zipfile.ZipFile(io.BytesIO(export.content)).read("org.json"))
    assert [p["name"] for p in org_json["personas"]] == ["Org shared"]

    imported = client.post(
        "/api/v1/orgs/import", data={"name": "Persona Bundle Org Reimport"},
        files={"file": ("bundle.zip", export.content, "application/zip")}, headers=auth_headers(admin_token),
    )
    assert imported.status_code == 201, imported.text
    new_org_id = uuid.UUID(imported.json()["organization"]["id"])

    with SessionLocal() as db:
        names = [t.name for t in db.scalars(
            select(PersonaTypeDefinition).where(PersonaTypeDefinition.organization_id == new_org_id)
            .order_by(PersonaTypeDefinition.sort_order)
        )]
        assert names == ["Primary", "Secondary", "Negative", "Edge case"]  # no duplicates from seeding + import
        personas = db.scalars(select(Persona).where(Persona.organization_id == new_org_id)).all()
        assert len(personas) == 1
        version = get_current_persona_version(db, personas[0].id)
        assert version.name == "Org shared" and version.weight == 4.0 and version.status == PersonaStatus.RETIRED
        assert version.org_type_id is not None
