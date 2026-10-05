"""Tests for Stakeholder Need bundle export/import (`need_export.py`): a
project's needs, their "has need" holders, "gives rise to" Requirement codes and
attachments survive `GET /projects/{id}/export` + `POST /projects/import`; a
holder the target organisation lacks is skipped with a warning."""

from __future__ import annotations

import io
import json
import zipfile

from app.modules.stakeholders.tests.test_need_api import _create_need, _create_requirement, _needs
from app.modules.stakeholders.tests.test_persona_api import _create_org_persona, _setup
from app.modules.stakeholders.tests.test_stakeholder_api import _create_project_stakeholder
from tests.conftest import auth_headers


def test_project_export_import_round_trips_needs(client, admin_token):
    org, project, token = _setup(client, admin_token, "Need Bundle Co")
    h = auth_headers(token)
    persona = _create_org_persona(client, token, org["id"], name="Shared persona")
    stakeholder = _create_project_stakeholder(client, token, project["id"], name="Needy Person")
    requirement = _create_requirement(client, token, project["id"])
    need = _create_need(client, token, project["id"], name="Round trip need")
    url = f"{_needs(project['id'])}/{need['id']}"
    client.post(url + "/activate", headers=h)
    client.post(url + "/holders", json={"kind": "persona", "id": persona["id"]}, headers=h)
    client.post(url + "/holders", json={"kind": "stakeholder", "id": stakeholder["id"]}, headers=h)
    client.post(url + "/requirements", json={"requirement_id": requirement["id"]}, headers=h)
    client.post(url + "/files", files={"file": ("evidence.txt", b"site notes", "text/plain")}, headers=h)

    export = client.get(f"/api/v1/projects/{project['id']}/export", headers=h)
    assert export.status_code == 200
    exported = json.loads(zipfile.ZipFile(io.BytesIO(export.content)).read("project.json"))
    assert [n["name"] for n in exported["project_stakeholder_needs"]] == ["Round trip need"]

    imported = client.post(
        "/api/v1/projects/import", data={"organization_id": org["id"], "name": "Need Bundle Reimported"},
        files={"file": ("bundle.zip", export.content, "application/zip")}, headers=h,
    )
    assert imported.status_code == 201, imported.text
    assert imported.json()["warnings"] == []
    new_id = imported.json()["project"]["id"]

    needs = client.get(_needs(new_id), headers=h).json()
    assert len(needs) == 1 and needs[0]["name"] == "Round trip need" and needs[0]["status"] == "active"
    new_url = f"{_needs(new_id)}/{needs[0]['id']}"
    assert {(r["kind"], r["name"]) for r in client.get(new_url + "/holders", headers=h).json()} == {
        ("persona", "Shared persona"), ("stakeholder", "Needy Person"),
    }
    assert [r["unique_code"] for r in client.get(new_url + "/requirements", headers=h).json()] == [requirement["unique_code"]]
    assert [f["filename"] for f in client.get(new_url + "/files", headers=h).json()] == ["evidence.txt"]


def test_import_into_org_lacking_the_holder_warns_and_skips_the_link(client, admin_token):
    org, project, token = _setup(client, admin_token, "Need Bundle Warn Co")
    h = auth_headers(token)
    persona = _create_org_persona(client, token, org["id"], name="Only here")
    need = _create_need(client, token, project["id"])
    client.post(f"{_needs(project['id'])}/{need['id']}/holders", json={"kind": "persona", "id": persona["id"]}, headers=h)
    export = client.get(f"/api/v1/projects/{project['id']}/export", headers=h)

    other, _, other_token = _setup(client, admin_token, "Need Bundle Warn Target Co")
    imported = client.post(
        "/api/v1/projects/import", data={"organization_id": other["id"], "name": "Need Warn Reimport"},
        files={"file": ("bundle.zip", export.content, "application/zip")}, headers=auth_headers(other_token),
    )
    assert imported.status_code == 201, imported.text
    assert any("holder 'Only here' not found" in w for w in imported.json()["warnings"])
