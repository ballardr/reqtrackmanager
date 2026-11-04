"""Tests for Product Feedback bundle export/import (`export.py`): a project's requests (current content, status, owner,
external reference, tags, evidence) and its submission policy survive `GET /projects/{id}/export` +
`POST /projects/import`, the imported records are numbered afresh, and an organisation's inbox survives
`GET /orgs/{id}/export` + `POST /orgs/import`. Version history and comments deliberately do not travel (see
`export.py`). Every test builds its own organisation."""

from __future__ import annotations

import io
import json
import uuid
import zipfile

from sqlalchemy import select

from app.database import SessionLocal
from app.modules.product_feedback.models import EnhancementRequest, EnhancementRequestVersion
from app.modules.product_feedback.tests._helpers import (
    create_inbox_request,
    create_request,
    org_base,
    project_base,
    setup,
    transition,
)
from tests.conftest import auth_headers


def _export(client, token, url) -> bytes:
    resp = client.get(url, headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return resp.content


def _import_project(client, token, org_id, bundle: bytes, name: str) -> dict:
    resp = client.post(
        "/api/v1/projects/import", data={"organization_id": org_id, "name": name},
        files={"file": ("bundle.zip", bundle, "application/zip")}, headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["project"]


def _requests(client, token, project_id, **params) -> dict[str, dict]:
    resp = client.get(project_base(project_id) + "/requests", params=params, headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return {r["title"]: r for r in resp.json()}


def test_a_project_round_trips_its_requests_policy_and_evidence_numbered_afresh(client, admin_token):
    org, project, token = setup(client, admin_token, "Feedback Bundle Co")
    h = auth_headers(token)
    base = project_base(project["id"])
    kept = create_request(client, token, project["id"], title="Keep", external_ref_url="https://jira.example/P-1", external_ref_key="P-1")
    declined = create_request(client, token, project["id"], title="Decline")
    transition(client, token, base, declined["id"], "declined", "Not now.")
    client.put(f"{base}/requests/{kept['id']}", json={"description": "Second version."}, headers=h)
    client.post(f"{base}/requests/{kept['id']}/comments", json={"body": "Not carried"}, headers=h)
    client.post(f"{base}/requests/{kept['id']}/files", files={"file": ("e.txt", b"evidence", "text/plain")}, headers=h)
    archived = create_request(client, token, project["id"], title="Archived")
    client.post(f"{base}/requests/{archived['id']}/archive", headers=h)
    client.put(base + "/settings", json={"submission_policy": "triagers"}, headers=h)

    imported = _import_project(client, token, org["id"], _export(client, token, f"/api/v1/projects/{project['id']}/export"), "Restored")
    got = _requests(client, token, imported["id"], include_archived="true")
    assert set(got) == {"Keep", "Decline", "Archived"}
    assert got["Keep"]["description"] == "Second version." and got["Keep"]["status"] == "new"
    assert got["Keep"]["external_ref_key"] == "P-1" and got["Keep"]["version_number"] == 1
    assert got["Decline"]["status"] == "declined" and got["Decline"]["decline_reason"] == "Not now."
    assert got["Archived"]["is_archived"] is True
    assert sorted(r["unique_code"] for r in got.values()) == ["ENH-001", "ENH-002", "ENH-003"]
    assert client.get(project_base(imported["id"]) + "/settings", headers=h).json() == {"submission_policy": "triagers"}

    files = client.get(f"{project_base(imported['id'])}/requests/{got['Keep']['id']}/files", headers=h).json()
    assert len(files) == 1 and client.get(f"/api/v1/files/{files[0]['id']}", headers=h).content == b"evidence"
    assert client.get(f"{project_base(imported['id'])}/requests/{got['Keep']['id']}/comments", headers=h).json() == []


def test_the_original_code_travels_as_information_only(client, admin_token):
    org, project, token = setup(client, admin_token, "Feedback Bundle Code Co")
    create_request(client, token, project["id"], title="First")
    bundle = _export(client, token, f"/api/v1/projects/{project['id']}/export")
    with zipfile.ZipFile(io.BytesIO(bundle)) as archive:
        document = json.loads(archive.read("project.json"))
    sections = json.dumps(document)
    assert '"unique_code": "ENH-001"' in sections


def test_an_organisation_round_trips_its_inbox_numbered_afresh_and_a_reimport_does_not_double_it(client, admin_token):
    org, _, token = setup(client, admin_token, "Feedback Org Bundle Co")
    first = create_inbox_request(client, token, org["id"], title="Inbox one", description="Wanted.")
    create_inbox_request(client, token, org["id"], title="Inbox two")
    transition(client, token, org_base(org["id"]), first["id"], "declined", "Out of scope.")
    export = _export(client, token, f"/api/v1/orgs/{org['id']}/export")
    org_json = json.loads(zipfile.ZipFile(io.BytesIO(export)).read("org.json"))
    assert sorted(r["title"] for r in org_json["enhancement_requests"]) == ["Inbox one", "Inbox two"]

    imported = client.post(
        "/api/v1/orgs/import", data={"name": "Restored Feedback Org"},
        files={"file": ("bundle.zip", export, "application/zip")}, headers=auth_headers(admin_token),
    )
    assert imported.status_code == 201, imported.text
    new_org_id = uuid.UUID(imported.json()["organization"]["id"])
    with SessionLocal() as db:
        rows = db.execute(
            select(EnhancementRequest, EnhancementRequestVersion)
            .join(EnhancementRequestVersion, EnhancementRequestVersion.request_id == EnhancementRequest.id)
            .where(EnhancementRequest.organization_id == new_org_id, EnhancementRequestVersion.valid_to.is_(None))
        ).all()
    by_title = {v.title: (r, v) for r, v in rows}
    assert set(by_title) == {"Inbox one", "Inbox two"}
    request, version = by_title["Inbox one"]
    assert version.status.value == "declined" and version.decline_reason == "Out of scope."
    assert request.scope.value == "organization" and request.project_id is None
    assert sorted(r.unique_code for r, _ in rows) == ["ENH-001", "ENH-002"]
