"""Tests for Compliance's contribution to the global search: its four artefact types and the
"This standard" scope registered through the module's `search_scopes`.

Each test builds its own organisation or standards, so none depends on state left by another test or run.
"""

from __future__ import annotations

import uuid

from app.modules.compliance.tests.test_compliance_evidence_api import _create_evidence
from app.modules.compliance.tests.test_compliance_standards_api import (
    _create_requirement,
    _create_standard,
    _create_version,
)
from app.modules.compliance.tests.test_project_compliance_api import (
    _assign_standard_to_project,
    _setup_published_standard_with_tree,
)
from tests.conftest import auth_headers, create_org_admin_in, create_org_user, create_project, login

CLAUSE = "compliance_requirement"
ASSIGNED = "project_compliance_requirement"
ACTION = "compliance_required_action_assessment"


def _search(client, token, body, expect=200):
    resp = client.post("/api/v1/search", json=body, headers=auth_headers(token))
    assert resp.status_code == expect, resp.text
    return resp.json()


def _other_standard(client, token, org_id, name="Beta policy"):
    standard = _create_standard(client, token, org_id, reference=f"BETA-{uuid.uuid4().hex[:4]}", name=name)
    version = _create_version(client, token, org_id, standard["id"], version_label="3.0")
    _create_requirement(client, token, org_id, standard["id"], version["id"], name="Temperature limits elsewhere", reference="9.9")
    return standard


def test_clauses_and_assignments_are_found_and_a_standard_scope_keeps_only_that_standard(client, admin_token, org_id):
    standard, version, _parent, _child, _pa, _ca = _setup_published_standard_with_tree(client, admin_token, org_id)
    project = create_project(client, admin_token, org_id, name="Scope Project")
    _assign_standard_to_project(client, admin_token, org_id, project["id"], standard["id"], version["id"])
    other = _other_standard(client, admin_token, org_id)

    everywhere = _search(client, admin_token, {"q": "temperature", "scope": "all"})
    types = {c["type"]: c["count"] for c in everywhere["type_counts"]}
    assert types[CLAUSE] == 2 and types[ASSIGNED] == 1

    scope = f"compliance:standard:{standard['id']}"
    scoped = _search(client, admin_token, {"q": "temperature", "scope": scope})
    assert {c["type"]: c["count"] for c in scoped["type_counts"]} == {CLAUSE: 1, ASSIGNED: 1}
    clause = next(h for h in scoped["hits"] if h["type"] == CLAUSE)
    assert clause["code"] == "4.1" and clause["title"] == "Temperature" and clause["project_id"] is None
    assignment = next(h for h in scoped["hits"] if h["type"] == ASSIGNED)
    assert assignment["project_id"] == project["id"]

    beyond = _search(client, admin_token, {"q": "temperature", "scope": f"compliance:standard:{other['id']}"})
    assert {c["type"]: c["count"] for c in beyond["type_counts"]} == {CLAUSE: 1}


def test_a_standard_scope_does_not_search_types_the_standard_does_not_own(client, admin_token, org_id):
    standard, *_ = _setup_published_standard_with_tree(client, admin_token, org_id)
    project = create_project(client, admin_token, org_id, name="Evidence Scope Project")
    _create_evidence(client, admin_token, project["id"], title="Thermal test report")

    everywhere = _search(client, admin_token, {"q": "thermal test report", "scope": "all"})
    assert "compliance_evidence" in {c["type"] for c in everywhere["type_counts"]}
    scoped = _search(client, admin_token, {"q": "thermal test report", "scope": f"compliance:standard:{standard['id']}"})
    assert "compliance_evidence" not in {c["type"] for c in scoped["type_counts"]}


def test_a_standard_of_another_organisation_is_indistinguishable_from_a_missing_one(client, admin_token, org_id):
    other_org, other_token = create_org_admin_in(client, admin_token, "Compliance Scope Other Org")
    create_project(client, other_token, other_org["id"], "Other Org Project")
    foreign = _create_standard(client, other_token, other_org["id"], reference="FOREIGN-1", name="Foreign standard")
    _setup_published_standard_with_tree(client, admin_token, org_id)

    missing = _search(client, admin_token, {"q": "anything", "scope": f"compliance:standard:{uuid.uuid4()}"}, expect=404)
    denied = _search(client, admin_token, {"q": "anything", "scope": f"compliance:standard:{foreign['id']}"}, expect=404)
    assert missing == denied


def test_a_user_who_can_open_no_project_of_the_organisation_gets_not_found(client, admin_token, org_id):
    standard, *_ = _setup_published_standard_with_tree(client, admin_token, org_id)
    create_project(client, admin_token, org_id, name="Closed Project")
    email = f"nobody-{uuid.uuid4().hex[:6]}@example.com"
    create_org_user(client, admin_token, org_id, email)
    token = login(client, email, "Password123!")
    _search(client, token, {"q": "anything", "scope": f"compliance:standard:{standard['id']}"}, expect=404)


def test_the_scope_is_refused_while_the_module_is_off(client, admin_token, org_id):
    standard, *_ = _setup_published_standard_with_tree(client, admin_token, org_id)
    create_project(client, admin_token, org_id, name="Module Off Scope Project")
    scope = f"compliance:standard:{standard['id']}"
    _search(client, admin_token, {"q": "temperature", "scope": scope})
    resp = client.put(f"/api/v1/orgs/{org_id}/modules/compliance", json={"enabled": False}, headers=auth_headers(admin_token))
    assert resp.status_code == 200, resp.text
    try:
        _search(client, admin_token, {"q": "temperature", "scope": scope}, expect=404)
    finally:
        client.put(f"/api/v1/orgs/{org_id}/modules/compliance", json={"enabled": True}, headers=auth_headers(admin_token))
