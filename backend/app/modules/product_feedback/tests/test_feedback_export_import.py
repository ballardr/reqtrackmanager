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

import pytest
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
    assert [(r["system_name"], r["key"]) for r in got["Keep"]["external_refs"]] == [("Other", "P-1")]
    assert got["Keep"]["version_number"] == 1
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


def test_requesters_and_an_active_merge_round_trip_and_an_ended_merge_does_not(client, admin_token):
    from app.modules.product_feedback.tests._helpers import (
        add_requester,
        create_persona,
        create_stakeholder,
        get_demand,
        get_request,
        setup_with_people,
    )

    org, project, token = setup_with_people(client, admin_token, "Feedback Bundle Demand Co")
    pid, base, h = project["id"], project_base(project["id"]), auth_headers(token)
    canonical = create_request(client, token, pid, title="Canonical")
    duplicate = create_request(client, token, pid, title="Duplicate")
    ended = create_request(client, token, pid, title="Ended")
    ann = create_stakeholder(client, token, pid, "Ann", influence="High", org_id=org["id"])
    tech = create_persona(client, token, pid, "Technician", weight=2)
    assert add_requester(client, token, org["id"], pid, canonical["id"], "stakeholder", ann["id"]).status_code == 201
    assert add_requester(client, token, org["id"], pid, duplicate["id"], "persona", tech["id"]).status_code == 201
    for dup in (duplicate, ended):
        assert client.post(f"{base}/requests/{dup['id']}/merge", json={"canonical_id": canonical["id"]}, headers=h).status_code == 200
    assert client.post(f"{base}/requests/{ended['id']}/unmerge", headers=h).status_code == 200

    imported = _import_project(client, token, org["id"], _export(client, token, f"/api/v1/projects/{pid}/export"), "Restored Demand")
    got = _requests(client, token, imported["id"])
    assert got["Duplicate"]["status"] == "duplicate" and got["Duplicate"]["merged_into"]["id"] == got["Canonical"]["id"]
    assert got["Ended"]["status"] == "new" and got["Ended"]["merged_into"] is None
    demand = get_demand(client, token, imported["id"], got["Canonical"]["id"])
    assert {r["label"]: r["from_merge"] for r in demand["requesters"]} == {"Ann": False, "Technician": True}
    assert demand["weighted_demand"] == 3 + 2
    assert get_request(client, token, imported["id"], got["Canonical"]["id"])["merged_count"] == 1
    # The original project is untouched.
    assert get_request(client, token, pid, canonical["id"])["requester_count"] == 2


def test_an_inbox_merge_round_trips_through_the_organisation_bundle(client, admin_token):
    org, _, token = setup(client, admin_token, "Feedback Org Merge Bundle Co")
    keep = create_inbox_request(client, token, org["id"], title="Keep this", description="A")
    dup = create_inbox_request(client, token, org["id"], title="Same again", description="B")
    assert client.post(
        f"{org_base(org['id'])}/requests/{dup['id']}/merge", json={"canonical_id": keep["id"]}, headers=auth_headers(token),
    ).status_code == 200
    export = _export(client, token, f"/api/v1/orgs/{org['id']}/export")
    imported = client.post(
        "/api/v1/orgs/import", data={"name": "Restored Merge Org"},
        files={"file": ("bundle.zip", export, "application/zip")}, headers=auth_headers(admin_token),
    )
    assert imported.status_code == 201, imported.text
    new_org_id = uuid.UUID(imported.json()["organization"]["id"])
    from app.modules.product_feedback.models import EnhancementRequestMerge

    with SessionLocal() as db:
        merges = db.scalars(
            select(EnhancementRequestMerge).join(EnhancementRequest, EnhancementRequest.id == EnhancementRequestMerge.duplicate_id)
            .where(EnhancementRequest.organization_id == new_org_id, EnhancementRequestMerge.unmerged_at.is_(None))
        ).all()
        assert len(merges) == 1
        titles = {r.id: v.title for r, v in db.execute(
            select(EnhancementRequest, EnhancementRequestVersion)
            .join(EnhancementRequestVersion, EnhancementRequestVersion.request_id == EnhancementRequest.id)
            .where(EnhancementRequest.organization_id == new_org_id, EnhancementRequestVersion.valid_to.is_(None))
        )}
        assert titles[merges[0].canonical_id] == "Keep this" and titles[merges[0].duplicate_id] == "Same again"


def test_scoring_levels_round_trip_by_axis_and_name(client, admin_token):
    org, project, token = setup(client, admin_token, "Feedback Bundle Score Co")
    pid = project["id"]
    scheme = client.get(project_base(pid) + "/scoring-scheme", headers=auth_headers(token)).json()
    levels = {a["key"]: {lv["name"]: lv["id"] for lv in a["levels"]} for a in scheme["axes"]}
    create_request(
        client, token, pid, title="Scored", levels={
            "reach": levels["reach"]["Most"], "impact": levels["impact"]["Massive"],
            "confidence": levels["confidence"]["Medium"], "effort": levels["effort"]["Small"],
            "ease": levels["ease"]["Easy"],
        },
    )
    bundle = _export(client, token, f"/api/v1/projects/{pid}/export")
    with zipfile.ZipFile(io.BytesIO(bundle)) as archive:
        document = json.dumps(json.loads(archive.read("project.json")))
    assert '"effort": {"axis": "effort", "name": "Small"}' in document and '"ease": {"axis": "ease", "name": "Easy"}' in document
    assert '"score"' not in document and '"derived_levels"' not in document  # derived, never exported

    imported = _import_project(client, token, org["id"], bundle, "Restored Scores")
    copy = _requests(client, token, imported["id"])["Scored"]
    assert copy["levels"]["effort"] == levels["effort"]["Small"] and copy["levels"]["reach"] == levels["reach"]["Most"]
    assert copy["levels"]["ease"] == levels["ease"]["Easy"]
    assert copy["score"] is not None and copy["score"]["raw"] == pytest.approx(4 * 3 * 0.8 / 1)
