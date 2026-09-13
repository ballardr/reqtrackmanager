"""Tests for Phase 15's PDF/CSV compliance report generation
(docs/compliance-module-plan.md Phase 15; docs/Compliance_Module_
Requirements.md §29): `GET /projects/{id}/modules/compliance/reports/
{pdf,csv}` and `GET /orgs/{id}/modules/compliance/reports/{pdf,csv}`,
mirroring `tests/test_reports.py`'s own established assertions (valid PDF
magic bytes, CSV formula-injection neutralization) for the core
requirement-report generator this module's own report generator
(`app.modules.compliance.reports`) follows the same pattern as.
"""

from __future__ import annotations

import csv
import io

from app.database import SessionLocal
from app.models.project import Project
from app.modules.compliance.reports import _narrative_requirement_paragraph, collect_project_compliance_report
from app.modules.compliance.tests.test_compliance_standards_api import (
    _base,
    _create_action_type,
    _create_requirement,
    _create_standard,
    _create_version,
    _grant_compliance_manager,
)
from app.modules.compliance.tests.test_project_compliance_api import (
    _assign_standard_to_project,
    _project_base,
    _publish_version,
    _setup_published_standard_with_tree,
)
from tests.conftest import auth_headers, create_org_user, create_project, login


def _find_pcr(client, token, project_id, assignment_id, requirement_id):
    pcrs = client.get(
        f"{_project_base(project_id)}/project-compliance/{assignment_id}/requirements", headers=auth_headers(token)
    ).json()
    return next(p for p in pcrs if p["requirement_id"] == requirement_id)


def _project_with_assessment(client, admin_token, org_id, *, project_name="Compliance Report Project"):
    standard, version, parent, child, _pa, _ca = _setup_published_standard_with_tree(client, admin_token, org_id)
    project = create_project(client, admin_token, org_id, name=project_name)
    assignment = _assign_standard_to_project(client, admin_token, org_id, project["id"], standard["id"], version["id"])

    parent_pcr = _find_pcr(client, admin_token, project["id"], assignment["id"], parent["id"])
    na_resp = client.patch(
        f"{_project_base(project['id'])}/project-compliance/{assignment['id']}/requirements/{parent_pcr['id']}/applicability",
        json={"applicability": "not_applicable", "justification": '=HYPERLINK("https://evil.example","x")'},
        headers=auth_headers(admin_token),
    )
    assert na_resp.status_code == 200, na_resp.text

    child_pcr = _find_pcr(client, admin_token, project["id"], assignment["id"], child["id"])
    # §9: the parent's Not Applicable would otherwise be inherited by the
    # child — explicitly override the child back to Applicable so its own
    # compliance assessment below is a *reported* status, not blanked out
    # by inherited Not Applicable (also exercises the "Overridden"
    # applicability source in the report).
    override_resp = client.patch(
        f"{_project_base(project['id'])}/project-compliance/{assignment['id']}/requirements/{child_pcr['id']}/applicability",
        json={"applicability": "applicable"}, headers=auth_headers(admin_token),
    )
    assert override_resp.status_code == 200, override_resp.text
    assess_resp = client.patch(
        f"{_project_base(project['id'])}/project-compliance/{assignment['id']}/requirements/{child_pcr['id']}/assessment",
        json={"compliance_status": "non_compliant", "justification": "Awaiting retest"},
        headers=auth_headers(admin_token),
    )
    assert assess_resp.status_code == 200, assess_resp.text
    return project, standard, version


def test_project_compliance_pdf_report_is_a_valid_pdf(client, admin_token, org_id):
    project, standard, _version = _project_with_assessment(client, admin_token, org_id)
    resp = client.get(f"{_project_base(project['id'])}/reports/pdf", headers=auth_headers(admin_token))
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.content[:5] == b"%PDF-"
    assert len(resp.content) > 500


def test_project_compliance_csv_report_includes_assessment_and_neutralizes_injection(client, admin_token, org_id):
    project, standard, version = _project_with_assessment(client, admin_token, org_id)
    resp = client.get(f"{_project_base(project['id'])}/reports/csv", headers=auth_headers(admin_token))
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "text/csv; charset=utf-8"
    text = resp.content.decode("utf-8")

    rows = list(csv.reader(io.StringIO(text)))
    header = rows[0]
    assert header[0] == "Standard reference"
    data_rows = rows[1:]
    assert len(data_rows) == 2  # parent + child requirement

    # Phase 42: the "Requirement name" column was relabelled "Requirement
    # title" for clarity, since "Requirement path"/"Requirement reference"/
    # "Requirement title" otherwise leaves a reader guessing which column is
    # the human-readable one.
    assert "Requirement title" in header
    assert "Requirement name" not in header

    standard_reference_col = header.index("Standard reference")
    version_col = header.index("Version")
    status_col = header.index("Compliance status")
    applicability_col = header.index("Applicability")
    justification_col = header.index("Justification")
    assert all(r[standard_reference_col] == standard["reference"] for r in data_rows)
    assert all(r[version_col] == version["version_label"] for r in data_rows)

    non_compliant_row = next(r for r in data_rows if r[status_col] == "Non-compliant")
    assert non_compliant_row[justification_col] == "Awaiting retest"

    not_applicable_row = next(r for r in data_rows if r[applicability_col] == "Not applicable")
    # CSV formula/DDE injection guard (OWASP CSV injection, `services.
    # csv_safety.csv_safe`) — a justification starting with `=` must be
    # neutralized with a leading `'`, the same as core `tests/test_reports.
    # py::test_csv_report_neutralizes_formula_injection` already asserts
    # for the core requirement-report exporter this module's own generator
    # follows the same escaping discipline as.
    assert not_applicable_row[justification_col].startswith("'=HYPERLINK(")


def test_org_compliance_report_requires_compliance_manager(client, admin_token, org_id):
    _project_with_assessment(client, admin_token, org_id, project_name="Org Report Gating Project")

    manager_id = create_org_user(client, admin_token, org_id, "compliance.report.manager@example.com", role="member")
    _grant_compliance_manager(client, admin_token, org_id, manager_id)
    manager_token = login(client, "compliance.report.manager@example.com", "Password123!")

    manager_pdf = client.get(f"{_base(org_id)}/reports/pdf", headers=auth_headers(manager_token))
    assert manager_pdf.status_code == 200
    assert manager_pdf.content[:5] == b"%PDF-"

    create_org_user(client, admin_token, org_id, "plain.report.viewer@example.com", role="member")
    plain_token = login(client, "plain.report.viewer@example.com", "Password123!")
    forbidden = client.get(f"{_base(org_id)}/reports/pdf", headers=auth_headers(plain_token))
    assert forbidden.status_code == 403


def test_org_compliance_csv_report_lists_project_assignment_roll_up(client, admin_token, org_id):
    project, standard, version = _project_with_assessment(client, admin_token, org_id, project_name="Org CSV Roll-up Project")
    resp = client.get(f"{_base(org_id)}/reports/csv", headers=auth_headers(admin_token))
    assert resp.status_code == 200
    text = resp.content.decode("utf-8")
    rows = list(csv.reader(io.StringIO(text)))
    header, data_rows = rows[0], rows[1:]

    project_col = header.index("Project")
    standard_col = header.index("Standard reference")
    version_col = header.index("Version")
    non_compliant_col = header.index("Non-compliant count")

    row = next(r for r in data_rows if r[project_col] == project["name"])
    assert row[standard_col] == standard["reference"]
    assert row[version_col] == version["version_label"]
    assert row[non_compliant_col] == "1"


# --- Phase 42: narrative requirement cell (title always shown) ------------------


def test_narrative_requirement_paragraph_always_shows_title_and_folds_in_free_text_fields(client, admin_token, org_id):
    """Phase 42's core fix: a requirement with a `reference` set must still
    show its own `name` (title) in the PDF's requirement cell — the PDF's
    "Requirement" column used to be built from `_requirement_path`'s
    breadcrumb, which drops a leaf requirement's `name` whenever it also
    has a `reference` (a `reference` won at every level, leaf included).
    Also pins the narrative-cell format itself: title first, then each of
    reasoning/description/clarification/justification/notes present, in
    that order, bold-prefixed on its own line — the `docs/requirements.md`-
    style single-cell layout this phase replaces one-column-per-field with.
    """
    _create_action_type(client, admin_token, org_id, name="Verification")
    standard = _create_standard(client, admin_token, org_id, reference="NAR-1", name="Narrative Cell Standard")
    version = _create_version(client, admin_token, org_id, standard["id"], version_label="2.0")
    requirement = _create_requirement(
        client, admin_token, org_id, standard["id"], version["id"],
        name="Equipment shall meet IPX9 water ingress requirements", reference="3.2.1",
        description="Applies to all outdoor-rated enclosures.",
        reasoning="Protects electronics from high-pressure water jets.",
    )
    _publish_version(client, admin_token, org_id, standard["id"], version["id"])
    clarify_resp = client.patch(
        f"{_base(org_id)}/standards/{standard['id']}/versions/{version['id']}/requirements/{requirement['id']}/clarify",
        json={
            "name": requirement["name"], "reference": requirement["reference"],
            "description": requirement["description"], "reasoning": requirement["reasoning"],
            "clarification_note": "Clarified to also cover submersion testing.",
        },
        headers=auth_headers(admin_token),
    )
    assert clarify_resp.status_code == 200, clarify_resp.text

    project = create_project(client, admin_token, org_id, name="Narrative Cell Project")
    assignment = _assign_standard_to_project(client, admin_token, org_id, project["id"], standard["id"], version["id"])
    pcr = _find_pcr(client, admin_token, project["id"], assignment["id"], requirement["id"])
    assess_resp = client.patch(
        f"{_project_base(project['id'])}/project-compliance/{assignment['id']}/requirements/{pcr['id']}/assessment",
        json={"compliance_status": "non_compliant", "justification": "Failed retest", "notes": "Vendor re-run scheduled"},
        headers=auth_headers(admin_token),
    )
    assert assess_resp.status_code == 200, assess_resp.text

    db = SessionLocal()
    try:
        data = collect_project_compliance_report(db, db.get(Project, project["id"]))
    finally:
        db.close()

    row = next(r for r in data.requirement_rows if r.requirement_reference == "3.2.1")
    assert row.requirement_name == "Equipment shall meet IPX9 water ingress requirements"
    assert row.requirement_reasoning == "Protects electronics from high-pressure water jets."
    assert row.requirement_description == "Applies to all outdoor-rated enclosures."
    assert row.requirement_clarification == "Clarified to also cover submersion testing."

    text = _narrative_requirement_paragraph(row).text
    assert "3.2.1 Equipment shall meet IPX9 water ingress requirements" in text
    assert "<b>Reasoning:</b> Protects electronics from high-pressure water jets." in text
    assert "<b>Description:</b> Applies to all outdoor-rated enclosures." in text
    assert "<b>Clarification:</b> Clarified to also cover submersion testing." in text
    assert "<b>Justification:</b> Failed retest" in text
    assert "<b>Notes:</b> Vendor re-run scheduled" in text
    assert (
        text.index("Reasoning:") < text.index("Description:") < text.index("Clarification:")
        < text.index("Justification:") < text.index("Notes:")
    )


def test_narrative_requirement_paragraph_omits_empty_sections(client, admin_token, org_id):
    """A requirement with no reasoning/description/clarification set renders
    just its title line — no empty bold-prefixed "Reasoning:"/"Description:"/
    "Clarification:" sections — even though it does carry a justification
    (from the Not Applicable decision `_project_with_assessment`'s fixture
    sets), which is a genuinely different, present field and must still
    show."""
    project, _standard, _version = _project_with_assessment(client, admin_token, org_id, project_name="Narrative Omit Project")
    db = SessionLocal()
    try:
        data = collect_project_compliance_report(db, db.get(Project, project["id"]))
    finally:
        db.close()

    row = next(r for r in data.requirement_rows if r.requirement_reference == "4")
    assert row.requirement_reasoning == ""
    assert row.requirement_description == ""
    assert row.requirement_clarification == ""
    text = _narrative_requirement_paragraph(row).text
    assert "Reasoning:" not in text
    assert "Description:" not in text
    assert "Clarification:" not in text
    assert "Justification:" in text  # the Not Applicable decision's own justification is present and must still show
