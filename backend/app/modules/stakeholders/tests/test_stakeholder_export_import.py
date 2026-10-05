"""Tests for Stakeholder bundle export/import (`stakeholder_export.py`): a
project's stakeholders, type rows, attachments, scoring levels and "represents"
links survive `GET /projects/{id}/export` + `POST /projects/import`, and an
organisation's types and org stakeholders survive `GET /orgs/{id}/export` +
`POST /orgs/import`. Version history and comments deliberately don't travel
(see `stakeholder_export.py`)."""

from __future__ import annotations

import io
import json
import uuid
import zipfile

from sqlalchemy import select

from app.database import SessionLocal
from app.modules.stakeholders.enums import StakeholderStatus, TargetCadence
from app.modules.stakeholders.models import Stakeholder, StakeholderTypeDefinition
from app.modules.stakeholders.service import get_current_stakeholder_version
from app.modules.stakeholders.tests.test_persona_api import (
    _create_org_persona,
    _create_project_persona,
    _org_base,
    _project_base,
    _setup,
)
from app.modules.stakeholders.tests.test_stakeholder_api import (
    _create_org_stakeholder,
    _create_project_stakeholder,
    _levels,
)
from tests.conftest import auth_headers


def test_project_export_import_round_trips_stakeholders(client, admin_token):
    org, project, token = _setup(client, admin_token, "Stakeholder Bundle Project Co")
    h = auth_headers(token)
    base = _project_base(project["id"])
    lv = _levels(client, token, org["id"])

    local = client.post(base + "/stakeholder-types", json={"name": "Project-only"}, headers=h).json()
    org_persona = _create_org_persona(client, token, org["id"], name="Shared persona")
    own_persona = _create_project_persona(client, token, project["id"], name="Own persona")
    typed = _create_project_stakeholder(
        client, token, project["id"], name="Typed Person", stakeholder_type_id=local["id"],
        influence_level_id=lv["influence"]["High"], interest_level_id=lv["interest"]["Medium"],
    )
    client.post(f"{base}/stakeholders/{typed['id']}/activate", headers=h)
    for persona in (org_persona, own_persona):
        client.post(f"{base}/stakeholders/{typed['id']}/personas", json={"persona_id": persona["id"]}, headers=h)
    client.post(
        f"{base}/stakeholders/{typed['id']}/files", files={"file": ("brief.txt", b"stakeholder brief", "text/plain")}, headers=h,
    )

    export = client.get(f"/api/v1/projects/{project['id']}/export", headers=h)
    assert export.status_code == 200
    exported = json.loads(zipfile.ZipFile(io.BytesIO(export.content)).read("project.json"))
    assert [s["name"] for s in exported["project_stakeholders"]] == ["Typed Person"]

    imported = client.post(
        "/api/v1/projects/import", data={"organization_id": org["id"], "name": "Stakeholder Bundle Reimported"},
        files={"file": ("bundle.zip", export.content, "application/zip")}, headers=h,
    )
    assert imported.status_code == 201, imported.text
    assert imported.json()["warnings"] == []
    new_base = _project_base(imported.json()["project"]["id"])

    stakeholders = client.get(new_base + "/stakeholders?include_org=false", headers=h).json()
    assert len(stakeholders) == 1
    s = stakeholders[0]
    assert s["name"] == "Typed Person" and s["status"] == "active" and s["stakeholder_type_name"] == "Project-only"
    assert s["contact_info"] == "pat@authority.example.com, +1 555 0100" and s["target_cadence"] == "quarterly"
    assert s["influence_level_id"] == lv["influence"]["High"] and s["interest_level_id"] == lv["interest"]["Medium"]
    assert [f["filename"] for f in client.get(f"{new_base}/stakeholders/{s['id']}/files", headers=h).json()] == ["brief.txt"]
    represented = client.get(f"{new_base}/stakeholders/{s['id']}/personas", headers=h).json()
    assert {p["name"] for p in represented} == {"Shared persona", "Own persona"}


def test_project_import_into_org_lacking_the_persona_warns_and_skips_the_link(client, admin_token):
    org, project, token = _setup(client, admin_token, "Stakeholder Bundle Warn Co")
    h = auth_headers(token)
    org_persona = _create_org_persona(client, token, org["id"], name="Only here")
    stakeholder = _create_project_stakeholder(client, token, project["id"], name="Linked")
    client.post(
        f"{_project_base(project['id'])}/stakeholders/{stakeholder['id']}/personas",
        json={"persona_id": org_persona["id"]}, headers=h,
    )
    export = client.get(f"/api/v1/projects/{project['id']}/export", headers=h)

    other, _, other_token = _setup(client, admin_token, "Stakeholder Bundle Warn Target Co")
    imported = client.post(
        "/api/v1/projects/import", data={"organization_id": other["id"], "name": "Warn Target Reimport"},
        files={"file": ("bundle.zip", export.content, "application/zip")}, headers=auth_headers(other_token),
    )
    assert imported.status_code == 201, imported.text
    assert any("represented Persona 'Only here' not found" in w for w in imported.json()["warnings"])


def test_org_export_import_round_trips_types_and_org_stakeholders(client, admin_token):
    org, project, token = _setup(client, admin_token, "Stakeholder Bundle Org Co")
    h = auth_headers(token)
    created = client.post(_org_base(org["id"]) + "/stakeholder-types", json={"name": "Edge case"}, headers=h)
    assert created.status_code == 201, created.text
    persona = _create_org_persona(client, token, org["id"], name="Org persona")
    stakeholder = _create_org_stakeholder(
        client, token, org["id"], name="Org shared", stakeholder_type_id=created.json()["id"], target_cadence="monthly",
    )
    client.post(f"{_org_base(org['id'])}/stakeholders/{stakeholder['id']}/retire", headers=h)
    client.post(
        f"{_org_base(org['id'])}/stakeholders/{stakeholder['id']}/personas", json={"persona_id": persona["id"]}, headers=h
    )

    export = client.get(f"/api/v1/orgs/{org['id']}/export", headers=h)
    assert export.status_code == 200
    org_json = json.loads(zipfile.ZipFile(io.BytesIO(export.content)).read("org.json"))
    assert [s["name"] for s in org_json["stakeholders"]] == ["Org shared"]

    imported = client.post(
        "/api/v1/orgs/import", data={"name": "Stakeholder Bundle Org Reimport"},
        files={"file": ("bundle.zip", export.content, "application/zip")}, headers=auth_headers(admin_token),
    )
    assert imported.status_code == 201, imported.text
    new_org_id = uuid.UUID(imported.json()["organization"]["id"])

    with SessionLocal() as db:
        names = [t.name for t in db.scalars(
            select(StakeholderTypeDefinition).where(StakeholderTypeDefinition.organization_id == new_org_id)
            .order_by(StakeholderTypeDefinition.sort_order)
        )]
        assert names[-1] == "Edge case" and len(names) == len(set(names)) == 12  # no duplicates from seeding + import
        stakeholders = db.scalars(select(Stakeholder).where(Stakeholder.organization_id == new_org_id)).all()
        assert len(stakeholders) == 1
        version = get_current_stakeholder_version(db, stakeholders[0].id)
        assert version.name == "Org shared" and version.target_cadence == TargetCadence.MONTHLY
        assert version.status == StakeholderStatus.RETIRED and version.org_type_id is not None
