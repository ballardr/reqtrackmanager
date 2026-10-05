"""Tests for the §10.5 relationship part of the project bundle
(`relationship_export.py`): a project's Stakeholder/Persona relationships to its
Requirements survive `GET /projects/{id}/export` + `POST /projects/import`
(links to Pain Points and Decisions are exported too, but cannot be recreated
until those modules' own records travel in the bundle, so each is warned about),
only this project's links travel for a shared org-level holder, and a target the
destination lacks is skipped with a warning."""

from __future__ import annotations

import io
import json
import zipfile

from app.modules.stakeholders.tests.test_need_api import _create_requirement
from app.modules.stakeholders.tests.test_persona_api import _create_org_persona, _setup
from app.modules.stakeholders.tests.test_relationship_api import _add, _create_decision, _create_pain_point, _rels
from app.modules.stakeholders.tests.test_stakeholder_api import _create_project_stakeholder
from tests.conftest import auth_headers, create_project


def _export(client, token, project_id):
    resp = client.get(f"/api/v1/projects/{project_id}/export", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return resp.content


def _import(client, token, org_id, name, content):
    resp = client.post(
        "/api/v1/projects/import", data={"organization_id": org_id, "name": name},
        files={"file": ("bundle.zip", content, "application/zip")}, headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_project_export_import_round_trips_relationships(client, admin_token):
    org, project, token = _setup(client, admin_token, "Rel Bundle Co")
    h = auth_headers(token)
    stakeholder = _create_project_stakeholder(client, token, project["id"], name="Bundled Person")
    persona = _create_org_persona(client, token, org["id"], name="Bundled Persona")
    point = _create_pain_point(client, token, org["id"], project["id"], "Bundled pain")
    decision = _create_decision(client, token, org["id"], project["id"], "Bundled decision")
    requirement = _create_requirement(client, token, project["id"])
    for holder, holder_id, kind, target_type, target_id in (
        ("stakeholder", stakeholder["id"], "experiences_pain_point", "pain_point", point["id"]),
        ("stakeholder", stakeholder["id"], "consulted_on_decision", "decision", decision["id"]),
        ("stakeholder", stakeholder["id"], "approves", "requirement", requirement["id"]),
        ("persona", persona["id"], "affected_by_requirement", "requirement", requirement["id"]),
    ):
        assert _add(client, token, project["id"], holder, holder_id, kind, target_type, target_id).status_code == 201

    content = _export(client, token, project["id"])
    exported = json.loads(zipfile.ZipFile(io.BytesIO(content)).read("project.json"))
    assert len(exported["project_stakeholder_relationships"]) == 4

    result = _import(client, token, org["id"], "Rel Bundle Reimported", content)
    new_id = result["project"]["id"]
    # Pain Points and Decisions are not part of the project bundle yet (their modules have no bundle hooks), so
    # those two links cannot be recreated: each is reported rather than silently dropped.
    assert len(result["warnings"]) == 2 and all("not found or ambiguous" in w for w in result["warnings"])

    new_stakeholder = next(
        s for s in client.get(f"/api/v1/projects/{new_id}/modules/stakeholders/stakeholders", headers=h).json()
        if s["name"] == "Bundled Person"
    )
    got = {(r["kind"], r["target_type"]) for r in client.get(_rels(new_id, "stakeholder", new_stakeholder["id"]), headers=h).json()}
    assert got == {("approves", "requirement")}
    # The shared org persona's link is re-created for the new project only.
    assert [r["kind"] for r in client.get(_rels(new_id, "persona", persona["id"]), headers=h).json()] == ["affected_by_requirement"]


def test_a_shared_holder_exports_only_this_projects_links(client, admin_token):
    org, project_a, token = _setup(client, admin_token, "Rel Bundle Shared Co")
    project_b = create_project(client, token, org["id"], "Rel Bundle Shared B")
    persona = _create_org_persona(client, token, org["id"], name="Everywhere")
    req_a = _create_requirement(client, token, project_a["id"], "A requirement")
    req_b = _create_requirement(client, token, project_b["id"], "B requirement")
    _add(client, token, project_a["id"], "persona", persona["id"], "provides_requirement", "requirement", req_a["id"])
    _add(client, token, project_b["id"], "persona", persona["id"], "provides_requirement", "requirement", req_b["id"])
    exported = json.loads(zipfile.ZipFile(io.BytesIO(_export(client, token, project_a["id"]))).read("project.json"))
    assert [e["target_ref"] for e in exported["project_stakeholder_relationships"]] == [req_a["unique_code"]]


def test_import_without_the_target_warns_and_skips(client, admin_token):
    org, project, token = _setup(client, admin_token, "Rel Bundle Warn Co")
    stakeholder = _create_project_stakeholder(client, token, project["id"], name="Warned Person")
    point = _create_pain_point(client, token, org["id"], project["id"], "Soon missing pain")
    _add(client, token, project["id"], "stakeholder", stakeholder["id"], "experiences_pain_point", "pain_point", point["id"])
    content = _export(client, token, project["id"])

    # The destination has no such Pain Point.
    other, _, other_token = _setup(client, admin_token, "Rel Bundle Warn Target Co")
    result = _import(client, other_token, other["id"], "Rel Warn Reimport", content)
    assert any("Soon missing pain" in w and "skipped" in w for w in result["warnings"])
