"""Tests for Compliance's record tables: Evidence exports as the CSV it imports (a row with a code updates through the
endpoints' own edit path, a blank code creates, the expiry date is revalidation-only), and the standard requirement, a
project's assessment of it and the assessment of one of its required actions export read-only (they have no
`PREFIX-nnn` code, so the Code column holds the clause reference and a file cannot update them). Each test builds its
own projects in the shared test organisation, so none depends on state left by another test.
"""

from __future__ import annotations

import csv
import io
import uuid
from datetime import date, timedelta

from app.database import SessionLocal
from app.models.audit import AuditEvent
from app.modules.compliance.tests.test_project_compliance_api import (
    _assign_project_role,
    _assign_standard_to_project,
    _project_base,
    _setup_published_standard_with_tree,
)
from tests.conftest import auth_headers, create_org_user, create_project, login

EVIDENCE, ASSESSMENT, ACTION, REQUIREMENT = (
    "compliance_evidence", "project_compliance_requirement", "compliance_required_action_assessment", "compliance_requirement",
)


def _records(project_id: str, record_type: str) -> str:
    return f"/api/v1/projects/{project_id}/records/{record_type}"


def _rows(resp) -> list[dict]:
    assert resp.status_code == 200, resp.text
    return list(csv.DictReader(io.StringIO(resp.content.decode("utf-8-sig"))))


def _export(client, token, project_id, record_type, **params):
    return client.get(f"{_records(project_id, record_type)}/export", params=params, headers=auth_headers(token))


def _import(client, token, project_id, record_type, text: str, *, apply: bool = False):
    return client.post(
        f"{_records(project_id, record_type)}/import", params={"dry_run": "false" if apply else "true"},
        files={"file": ("records.csv", text.encode("utf-8"), "text/csv")}, headers=auth_headers(token),
    )


def _csv(header: list[str], *rows: list[str]) -> str:
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(header)
    writer.writerows(rows)
    return out.getvalue()


def _evidence(client, token, project_id, **extra) -> dict:
    resp = client.post(f"{_project_base(project_id)}/evidence", json={"title": "IPX9 Test Certificate", **extra}, headers=auth_headers(token))
    assert resp.status_code == 201, resp.text
    return resp.json()


def _get_evidence(client, token, project_id, evidence_id) -> dict:
    return client.get(f"{_project_base(project_id)}/evidence/{evidence_id}", headers=auth_headers(token)).json()


def _assigned_project(client, admin_token, org_id):
    standard, version, parent, child, parent_action, child_action = _setup_published_standard_with_tree(client, admin_token, org_id)
    project = create_project(client, admin_token, org_id, name=f"Tables {uuid.uuid4().hex[:6]}")
    assignment = _assign_standard_to_project(client, admin_token, org_id, project["id"], standard["id"], version["id"])
    return project, assignment, standard, version, parent, child


# --- Evidence ----------------------------------------------------------------------------------------------------


def test_evidence_exports_with_its_code_and_reimporting_it_unchanged_changes_nothing(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id, name="Evidence Tables A")
    first = _evidence(client, admin_token, project["id"], issuing_organisation="Acme Labs", issued_date="2026-01-01")
    second = _evidence(client, admin_token, project["id"], title="Second", expiry_date="2099-01-01")
    resp = _export(client, admin_token, project["id"], EVIDENCE)
    rows = _rows(resp)
    assert {r["code"] for r in rows} == {first["unique_code"], second["unique_code"]}
    assert {r["code"][:4] for r in rows} == {"EVD-"}
    by_title = {r["title"]: r for r in rows}
    assert by_title["IPX9 Test Certificate"]["issuing_organisation"] == "Acme Labs"
    assert by_title["Second"]["validity"] == "Valid" and by_title["IPX9 Test Certificate"]["validity"] == "No expiry"
    preview = _import(client, admin_token, project["id"], EVIDENCE, resp.content.decode("utf-8-sig")).json()
    assert (preview["created"], preview["updated"], preview["unchanged"], preview["failed"]) == (0, 0, 2, 0), preview


def test_editing_a_cell_updates_that_evidence_and_records_the_audit_event(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id, name="Evidence Tables B")
    evidence = _evidence(client, admin_token, project["id"])
    text = _csv(["code", "notes"], [evidence["unique_code"], "Lab report v2 attached"])
    assert _import(client, admin_token, project["id"], EVIDENCE, text).json()["updated"] == 1
    assert _get_evidence(client, admin_token, project["id"], evidence["id"])["notes"] == ""
    assert _import(client, admin_token, project["id"], EVIDENCE, text, apply=True).json()["updated"] == 1
    assert _get_evidence(client, admin_token, project["id"], evidence["id"])["notes"] == "Lab report v2 attached"
    db = SessionLocal()
    try:
        actions = {e.action for e in db.query(AuditEvent).filter(AuditEvent.entity_id == evidence["id"]).all()}
    finally:
        db.close()
    assert {"created", "updated"} <= actions


def test_a_blank_code_creates_evidence_provided_by_the_importer_and_expiry_is_set_at_creation(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id, name="Evidence Tables C")
    text = _csv(["code", "title", "expiry_date"], ["", "From a file", "2099-06-30"])
    assert _import(client, admin_token, project["id"], EVIDENCE, text).json()["created"] == 1
    assert _rows(_export(client, admin_token, project["id"], EVIDENCE)) == [], "a preview must not create"
    assert _import(client, admin_token, project["id"], EVIDENCE, text, apply=True).json()["created"] == 1
    row = _rows(_export(client, admin_token, project["id"], EVIDENCE))[0]
    assert (row["title"], row["expiry_date"], row["status"]) == ("From a file", "2099-06-30", "Active")
    assert row["provided_at"].endswith("+00:00")
    missing = _import(client, admin_token, project["id"], EVIDENCE, _csv(["code", "notes"], ["", "no title"])).json()
    assert missing["failed"] == 1


def test_the_expiry_date_of_existing_evidence_changes_only_by_revalidation(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id, name="Evidence Tables D")
    evidence = _evidence(client, admin_token, project["id"], expiry_date="2099-01-01")
    refused = _import(
        client, admin_token, project["id"], EVIDENCE, _csv(["code", "expiry_date"], [evidence["unique_code"], "2100-01-01"]), apply=True,
    ).json()
    assert refused["failed"] == 1 and "revalidating" in refused["rows"][0]["message"]
    assert _get_evidence(client, admin_token, project["id"], evidence["id"])["expiry_date"] == "2099-01-01"
    same = _import(client, admin_token, project["id"], EVIDENCE, _csv(["code", "expiry_date"], [evidence["unique_code"], "2099-01-01"])).json()
    assert same["unchanged"] == 1


def test_only_a_compliance_officer_may_import_evidence(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id, name="Evidence Tables E")
    email = f"ev-member-{uuid.uuid4().hex[:6]}@example.com"
    member_id = create_org_user(client, admin_token, org_id, email, role="member")
    _assign_project_role(client, admin_token, project["id"], member_id, "member")
    member = login(client, email, "Password123!")
    columns = client.get(f"{_records(project['id'], EVIDENCE)}/columns", headers=auth_headers(member)).json()
    assert columns["importable"] is True and columns["can_import"] is False


def test_the_evidence_lists_filters_reach_the_export(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id, name="Evidence Tables F")
    soon = (date.today() + timedelta(days=5)).isoformat()
    expiring = _evidence(client, admin_token, project["id"], title="Expiring cert", expiry_date=soon)
    other = _evidence(client, admin_token, project["id"], title="Other cert")
    assert [r["code"] for r in _rows(_export(client, admin_token, project["id"], EVIDENCE, validity="expiring_soon"))] == [expiring["unique_code"]]
    assert [r["code"] for r in _rows(_export(client, admin_token, project["id"], EVIDENCE, search="other"))] == [other["unique_code"]]
    client.post(f"{_project_base(project['id'])}/evidence/{other['id']}/archive", headers=auth_headers(admin_token))
    assert len(_rows(_export(client, admin_token, project["id"], EVIDENCE))) == 1
    assert len(_rows(_export(client, admin_token, project["id"], EVIDENCE, include_archived="true"))) == 2
    assert _export(client, admin_token, project["id"], EVIDENCE, nonsense="1").status_code == 422


# --- The read-only tables -----------------------------------------------------------------------------------------


def test_a_projects_assessments_export_with_the_clause_reference_as_the_code(client, admin_token, org_id):
    project, assignment, standard, version, parent, child = _assigned_project(client, admin_token, org_id)
    rows = _rows(_export(client, admin_token, project["id"], ASSESSMENT))
    assert {r["code"] for r in rows} == {"4", "4.1"}
    row = next(r for r in rows if r["code"] == "4.1")
    assert (row["standard"], row["version"], row["requirement"]) == ("EMC-1", "2.0", "Temperature")
    assert (row["applicability"], row["compliance_status"], row["approval_state"]) == ("Applicable", "Not started", "Not assessed")
    assert [r["code"] for r in _rows(_export(client, admin_token, project["id"], ASSESSMENT, search="temperature"))] == ["4.1"]
    assert len(_rows(_export(client, admin_token, project["id"], ASSESSMENT, assignment=assignment["id"]))) == 2
    assert _rows(_export(client, admin_token, project["id"], ASSESSMENT, assignment=str(uuid.uuid4()))) == []
    assert _rows(_export(client, admin_token, project["id"], ASSESSMENT, status="compliant")) == []
    assert _export(client, admin_token, project["id"], ASSESSMENT, assignment="nonsense").status_code == 422


def test_required_action_assessments_export_and_the_outstanding_filter_drops_completed_ones(client, admin_token, org_id):
    project, assignment, _standard, _version, _parent, child = _assigned_project(client, admin_token, org_id)
    rows = _rows(_export(client, admin_token, project["id"], ACTION))
    assert {r["required_action"] for r in rows} == {"Section review", "Run thermal test"}
    assert all(r["completed"] == "false" and r["mandatory"] == "true" for r in rows)
    assert len(_rows(_export(client, admin_token, project["id"], ACTION, outstanding="true"))) == 2
    pcrs = client.get(
        f"{_project_base(project['id'])}/project-compliance/{assignment['id']}/requirements", headers=auth_headers(admin_token),
    ).json()
    pcr = next(p for p in pcrs if p["requirement_id"] == child["id"])
    base = f"{_project_base(project['id'])}/project-compliance/{assignment['id']}/requirements/{pcr['id']}/required-action-assessments"
    assessment = client.get(base, headers=auth_headers(admin_token)).json()[0]
    done = client.post(f"{base}/{assessment['id']}/complete", json={}, headers=auth_headers(admin_token))
    assert done.status_code == 200, done.text
    outstanding = _rows(_export(client, admin_token, project["id"], ACTION, outstanding="true"))
    assert [r["required_action"] for r in outstanding] == ["Section review"]
    completed = next(r for r in _rows(_export(client, admin_token, project["id"], ACTION)) if r["completed"] == "true")
    assert completed["required_action"] == "Run thermal test" and completed["completed_at"].endswith("+00:00")


def test_the_requirements_of_assigned_versions_export_with_the_organisation_qualified_clause_reference(client, admin_token, org_id):
    project, _assignment, *_ = _assigned_project(client, admin_token, org_id)
    rows = _rows(_export(client, admin_token, project["id"], REQUIREMENT))
    organisation_code = client.get(f"/api/v1/orgs/{org_id}", headers=auth_headers(admin_token)).json()["code"]
    assert {r["code"] for r in rows} == {f"{organisation_code}-4", f"{organisation_code}-4.1"}
    assert {r["version_status"] for r in rows} == {"Published"}


def test_the_organisation_lists_every_standards_requirements_narrowed_by_standard_and_version(client, admin_token, org_id):
    standard, version, *_ = _setup_published_standard_with_tree(client, admin_token, org_id)
    path = f"/api/v1/orgs/{org_id}/records/{REQUIREMENT}"
    everything = client.get(f"{path}/export", headers=auth_headers(admin_token))
    assert {r["requirement"] for r in _rows(everything)} >= {"Environmental requirements", "Temperature"}
    params = {"standard": standard["id"], "version": version["id"], "search": "temp"}
    narrowed = client.get(f"{path}/export", params=params, headers=auth_headers(admin_token))
    assert [r["requirement"] for r in _rows(narrowed)] == ["Temperature"]
    assert client.get(f"{path}/export", params={"nonsense": "1"}, headers=auth_headers(admin_token)).status_code == 422
    columns = client.get(f"{path}/columns", headers=auth_headers(admin_token)).json()
    assert columns["importable"] is False and "import the standard itself" in columns["not_importable_reason"]


def test_the_read_only_types_refuse_an_import_with_their_reason(client, admin_token, org_id):
    project, *_ = _assigned_project(client, admin_token, org_id)
    for record_type in (ASSESSMENT, ACTION, REQUIREMENT):
        resp = _import(client, admin_token, project["id"], record_type, _csv(["code", "notes"], ["4.1", "x"]), apply=True)
        assert resp.status_code == 422, record_type
        columns = client.get(f"{_records(project['id'], record_type)}/columns", headers=auth_headers(admin_token)).json()
        assert columns["importable"] is False and columns["not_importable_reason"], record_type


def test_a_project_cannot_export_another_projects_assessments(client, admin_token, org_id):
    project, *_ = _assigned_project(client, admin_token, org_id)
    other = create_project(client, admin_token, org_id, name="Tables Other Project")
    assert _rows(_export(client, admin_token, other["id"], ASSESSMENT)) == []
    assert _rows(_export(client, admin_token, other["id"], ACTION)) == []
    assert len(_rows(_export(client, admin_token, project["id"], ASSESSMENT))) == 2
