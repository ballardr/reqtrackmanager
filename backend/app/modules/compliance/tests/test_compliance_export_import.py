"""Tests for Phase 15's export/import bundle integration
(docs/compliance-module-plan.md Phase 15; docs/Compliance_Module_
Requirements.md §29): a project's compliance assessment (assignments,
per-requirement applicability/status/approval, required-action
assessments, evidence with revalidation history, and project-level
reviews) survives `GET /projects/{id}/export` + `POST /projects/import`
intact (`app.services.project_export`'s own Phase 15 notes), and an
organisation's compliance standards/versions/requirements/required
actions/vocabularies/cross-standard mappings survive `GET /orgs/{id}/export`
+ `POST /orgs/import` intact (`app.services.org_export`'s own Phase 15
notes).

Reuses `test_project_compliance_api.py`'s/`test_compliance_standards_api.
py`'s existing small API helpers for setup, the same way this module's
other test files already do.
"""

from __future__ import annotations

import io
import zipfile
from datetime import date, timedelta

from app.modules.compliance.tests.test_compliance_standards_api import (
    _base,
    _create_action_type,
    _create_requirement,
    _create_standard,
    _create_version,
)
from app.modules.compliance.tests.test_project_compliance_api import (
    _assign_standard_to_project,
    _project_base,
    _publish_version,
    _setup_published_standard_with_tree,
)
from tests.conftest import auth_headers, create_org_admin_in, create_project

TODAY = date.today()


def _find_pcr(client, token, project_id, assignment_id, requirement_id):
    pcrs = client.get(
        f"{_project_base(project_id)}/project-compliance/{assignment_id}/requirements", headers=auth_headers(token)
    ).json()
    return next(p for p in pcrs if p["requirement_id"] == requirement_id)


def _merge_preview(client, token, target_org_id, bundle_bytes):
    resp = client.post(
        f"/api/v1/orgs/{target_org_id}/import/preview",
        files={"file": ("bundle.zip", bundle_bytes, "application/zip")},
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["conflicts"]


def _merge(client, token, target_org_id, bundle_bytes, resolutions):
    import json

    resp = client.post(
        f"/api/v1/orgs/{target_org_id}/import/merge",
        files={"file": ("bundle.zip", bundle_bytes, "application/zip")},
        data={"resolutions": json.dumps(resolutions)},
        headers=auth_headers(token),
    )
    return resp


def test_project_export_import_round_trips_compliance_assessment(client, admin_token, org_id):
    """Builds a project with a real compliance assessment — an assignment,
    a Not Applicable parent requirement, a Compliant child requirement, a
    completed required-action assessment, evidence (with a revalidation)
    linked to both, and a scheduled review — exports it, imports it as a
    new project in the same organisation (which already has the assigned
    standard, since it wasn't touched by this import), and asserts every
    one of those facts survives intact."""
    standard, version, parent, child, _pa, child_action = _setup_published_standard_with_tree(client, admin_token, org_id)
    project = create_project(client, admin_token, org_id, name="Compliance Export Source")
    assignment = _assign_standard_to_project(client, admin_token, org_id, project["id"], standard["id"], version["id"])

    parent_pcr = _find_pcr(client, admin_token, project["id"], assignment["id"], parent["id"])
    child_pcr = _find_pcr(client, admin_token, project["id"], assignment["id"], child["id"])

    na_resp = client.patch(
        f"{_project_base(project['id'])}/project-compliance/{assignment['id']}/requirements/{parent_pcr['id']}/applicability",
        json={"applicability": "not_applicable", "justification": "Not used in this product line"},
        headers=auth_headers(admin_token),
    )
    assert na_resp.status_code == 200, na_resp.text

    assess_resp = client.patch(
        f"{_project_base(project['id'])}/project-compliance/{assignment['id']}/requirements/{child_pcr['id']}/assessment",
        json={"compliance_status": "compliant", "notes": "Thermal test passed"},
        headers=auth_headers(admin_token),
    )
    assert assess_resp.status_code == 200, assess_resp.text

    assessments = client.get(
        f"{_project_base(project['id'])}/project-compliance/{assignment['id']}/requirements/{child_pcr['id']}/"
        "required-action-assessments",
        headers=auth_headers(admin_token),
    ).json()
    action_assessment = next(a for a in assessments if a["required_action_id"] == child_action["id"])
    due_resp = client.patch(
        f"{_project_base(project['id'])}/project-compliance/{assignment['id']}/requirements/{child_pcr['id']}/"
        f"required-action-assessments/{action_assessment['id']}",
        json={"due_date": str(TODAY + timedelta(days=30)), "notes": "Book the thermal chamber"},
        headers=auth_headers(admin_token),
    )
    assert due_resp.status_code == 200, due_resp.text
    complete_resp = client.post(
        f"{_project_base(project['id'])}/project-compliance/{assignment['id']}/requirements/{child_pcr['id']}/"
        f"required-action-assessments/{action_assessment['id']}/complete",
        headers=auth_headers(admin_token),
    )
    assert complete_resp.status_code == 200, complete_resp.text

    evidence_resp = client.post(
        f"{_project_base(project['id'])}/evidence",
        json={
            "title": "Thermal Test Certificate", "issuing_organisation": "Acme Test Labs",
            "issued_date": str(TODAY), "expiry_date": str(TODAY + timedelta(days=300)),
            "project_compliance_requirement_ids": [child_pcr["id"]],
            "required_action_assessment_ids": [action_assessment["id"]],
        },
        headers=auth_headers(admin_token),
    )
    assert evidence_resp.status_code == 201, evidence_resp.text
    evidence = evidence_resp.json()
    revalidate_resp = client.post(
        f"{_project_base(project['id'])}/evidence/{evidence['id']}/revalidate",
        json={"new_expiry_date": str(TODAY + timedelta(days=700)), "justification": "Retested, extended validity"},
        headers=auth_headers(admin_token),
    )
    assert revalidate_resp.status_code == 200, revalidate_resp.text

    review_resp = client.post(
        f"{_project_base(project['id'])}/project-compliance/{assignment['id']}/reviews",
        json={"frequency_label": "Annual", "recurrence_days": 365, "next_due_date": str(TODAY + timedelta(days=365)), "notes": "Yearly check"},
        headers=auth_headers(admin_token),
    )
    assert review_resp.status_code == 201, review_resp.text

    export_resp = client.get(f"/api/v1/projects/{project['id']}/export", headers=auth_headers(admin_token))
    assert export_resp.status_code == 200
    zf = zipfile.ZipFile(io.BytesIO(export_resp.content))
    import json

    exported = json.loads(zf.read("project.json"))
    assert exported["compliance_project_compliances"], "compliance assignment missing from export"
    assert exported["compliance_evidence"], "compliance evidence missing from export"

    import_resp = client.post(
        "/api/v1/projects/import",
        data={"organization_id": org_id, "name": "Compliance Export Reimported"},
        files={"file": ("bundle.zip", export_resp.content, "application/zip")},
        headers=auth_headers(admin_token),
    )
    assert import_resp.status_code == 201, import_resp.text
    result = import_resp.json()
    assert result["warnings"] == []
    new_project = result["project"]

    new_assignments = client.get(
        f"{_project_base(new_project['id'])}/project-compliance", headers=auth_headers(admin_token)
    ).json()
    assert len(new_assignments) == 1
    new_assignment = new_assignments[0]
    assert new_assignment["standard_version_id"] == version["id"]  # same org still has this exact version

    new_parent_pcr = _find_pcr(client, admin_token, new_project["id"], new_assignment["id"], parent["id"])
    assert new_parent_pcr["explicit_applicability"] == "not_applicable"
    assert new_parent_pcr["justification"] == "Not used in this product line"

    new_child_pcr = _find_pcr(client, admin_token, new_project["id"], new_assignment["id"], child["id"])
    assert new_child_pcr["compliance_status"] == "compliant"
    assert new_child_pcr["notes"] == "Thermal test passed"

    new_assessments = client.get(
        f"{_project_base(new_project['id'])}/project-compliance/{new_assignment['id']}/requirements/"
        f"{new_child_pcr['id']}/required-action-assessments",
        headers=auth_headers(admin_token),
    ).json()
    new_action_assessment = next(a for a in new_assessments if a["required_action_id"] == child_action["id"])
    assert new_action_assessment["is_completed"] is True
    assert new_action_assessment["due_date"] == str(TODAY + timedelta(days=30))
    assert new_action_assessment["notes"] == "Book the thermal chamber"

    new_evidence_list = client.get(f"{_project_base(new_project['id'])}/evidence", headers=auth_headers(admin_token)).json()
    assert len(new_evidence_list) == 1
    new_evidence = new_evidence_list[0]
    assert new_evidence["title"] == "Thermal Test Certificate"
    assert new_evidence["expiry_date"] == str(TODAY + timedelta(days=700))  # revalidated value, not the original
    assert len(new_evidence["linked_requirement_ids"]) == 1
    assert len(new_evidence["linked_required_action_assessment_ids"]) == 1

    revalidations = client.get(
        f"{_project_base(new_project['id'])}/evidence/{new_evidence['id']}/revalidations", headers=auth_headers(admin_token)
    ).json()
    assert len(revalidations) == 1
    assert revalidations[0]["previous_expiry_date"] == str(TODAY + timedelta(days=300))
    assert revalidations[0]["new_expiry_date"] == str(TODAY + timedelta(days=700))

    new_reviews = client.get(
        f"{_project_base(new_project['id'])}/project-compliance/{new_assignment['id']}/reviews",
        headers=auth_headers(admin_token),
    ).json()
    assert len(new_reviews) == 1
    assert new_reviews[0]["frequency_label"] == "Annual"
    assert new_reviews[0]["recurrence_days"] == 365


def test_project_export_import_skips_assignment_when_target_org_lacks_the_standard(client, admin_token, org_id):
    """§31/this module's own docstring: a project bundle never re-creates
    the standard it references — importing into an organisation that
    doesn't have it skips the assignment (and its assessment data)
    entirely, with a warning, rather than fabricating one."""
    standard, version, _parent, _child, _pa, _ca = _setup_published_standard_with_tree(client, admin_token, org_id)
    project = create_project(client, admin_token, org_id, name="Orphaned Assignment Source")
    _assign_standard_to_project(client, admin_token, org_id, project["id"], standard["id"], version["id"])

    export_resp = client.get(f"/api/v1/projects/{project['id']}/export", headers=auth_headers(admin_token))
    assert export_resp.status_code == 200

    from tests.conftest import create_org_admin_in

    other_org, other_org_admin_token = create_org_admin_in(client, admin_token, "Compliance-less Import Target")
    import_resp = client.post(
        "/api/v1/projects/import",
        data={"organization_id": other_org["id"], "name": "Orphaned Assignment Reimport"},
        files={"file": ("bundle.zip", export_resp.content, "application/zip")},
        headers=auth_headers(other_org_admin_token),
    )
    assert import_resp.status_code == 201, import_resp.text
    result = import_resp.json()
    assert any("does not exist in the target organisation" in w for w in result["warnings"])

    new_assignments = client.get(
        f"{_project_base(result['project']['id'])}/project-compliance", headers=auth_headers(other_org_admin_token)
    ).json()
    assert new_assignments == []


def test_org_export_import_round_trips_standards_and_mappings(client, admin_token, org_id):
    """Builds two compliance standards (with a published version, a
    hierarchical requirement tree, and required actions on one of them)
    plus a cross-standard requirement mapping between them, exports the
    organisation, imports it as a brand-new organisation, and asserts the
    full standard/version/requirement/required-action tree and the mapping
    both survive intact."""
    action_type = _create_action_type(client, admin_token, org_id, name="Inspection")
    standard_a = _create_standard(client, admin_token, org_id, reference="ORG-EXPORT-A", name="Standard A")
    version_a = _create_version(client, admin_token, org_id, standard_a["id"], version_label="1.0")
    parent = _create_requirement(client, admin_token, org_id, standard_a["id"], version_a["id"], name="Section 1", reference="1")
    child = _create_requirement(
        client, admin_token, org_id, standard_a["id"], version_a["id"],
        name="Clause 1.1", reference="1.1", parent_requirement_id=parent["id"],
    )
    action_resp = client.post(
        f"{_base(org_id)}/standards/{standard_a['id']}/versions/{version_a['id']}/requirements/{child['id']}/required-actions",
        json={"action_type_id": action_type["id"], "name": "Inspect enclosure", "is_mandatory": True},
        headers=auth_headers(admin_token),
    )
    assert action_resp.status_code == 201, action_resp.text
    _publish_version(client, admin_token, org_id, standard_a["id"], version_a["id"])

    standard_b = _create_standard(client, admin_token, org_id, reference="ORG-EXPORT-B", name="Standard B")
    version_b = _create_version(client, admin_token, org_id, standard_b["id"], version_label="1.0")
    other_requirement = _create_requirement(
        client, admin_token, org_id, standard_b["id"], version_b["id"], name="Equivalent clause", reference="9.9",
    )
    _publish_version(client, admin_token, org_id, standard_b["id"], version_b["id"])

    rel_type_resp = client.post(
        f"{_base(org_id)}/mapping-relationship-types", json={"name": "Equivalent", "implies_equivalence": True},
        headers=auth_headers(admin_token),
    )
    assert rel_type_resp.status_code == 201, rel_type_resp.text
    relationship_type = rel_type_resp.json()
    mapping_resp = client.post(
        f"{_base(org_id)}/requirement-mappings",
        json={
            "from_requirement_id": child["id"], "to_requirement_id": other_requirement["id"],
            "relationship_type_id": relationship_type["id"], "notes": "Same underlying obligation",
        },
        headers=auth_headers(admin_token),
    )
    assert mapping_resp.status_code == 201, mapping_resp.text

    export_resp = client.get(f"/api/v1/orgs/{org_id}/export", headers=auth_headers(admin_token))
    assert export_resp.status_code == 200
    zf = zipfile.ZipFile(io.BytesIO(export_resp.content))
    import json

    org_data = json.loads(zf.read("org.json"))
    assert len(org_data["compliance_standards"]) >= 2
    assert org_data["compliance_requirement_mappings"], "requirement mapping missing from export"

    import_resp = client.post(
        "/api/v1/orgs/import", data={"name": "Compliance Org Reimport"},
        files={"file": ("bundle.zip", export_resp.content, "application/zip")}, headers=auth_headers(admin_token),
    )
    assert import_resp.status_code == 201, import_resp.text
    new_org = import_resp.json()["organization"]

    new_standards = client.get(f"{_base(new_org['id'])}/standards", headers=auth_headers(admin_token)).json()
    new_standard_a = next(s for s in new_standards if s["reference"] == "ORG-EXPORT-A")
    new_standard_b = next(s for s in new_standards if s["reference"] == "ORG-EXPORT-B")

    new_versions_a = client.get(f"{_base(new_org['id'])}/standards/{new_standard_a['id']}/versions", headers=auth_headers(admin_token)).json()
    assert len(new_versions_a) == 1
    new_version_a = new_versions_a[0]
    assert new_version_a["status"] == "published"

    new_requirements_a = client.get(
        f"{_base(new_org['id'])}/standards/{new_standard_a['id']}/versions/{new_version_a['id']}/requirements",
        headers=auth_headers(admin_token),
    ).json()
    new_parent = next(r for r in new_requirements_a if r["reference"] == "1")
    new_child = next(r for r in new_requirements_a if r["reference"] == "1.1")
    assert new_child["parent_requirement_id"] == new_parent["id"]

    new_actions = client.get(
        f"{_base(new_org['id'])}/standards/{new_standard_a['id']}/versions/{new_version_a['id']}/requirements/"
        f"{new_child['id']}/required-actions",
        headers=auth_headers(admin_token),
    ).json()
    assert [a["name"] for a in new_actions] == ["Inspect enclosure"]

    new_versions_b = client.get(f"{_base(new_org['id'])}/standards/{new_standard_b['id']}/versions", headers=auth_headers(admin_token)).json()
    new_version_b = new_versions_b[0]
    new_requirements_b = client.get(
        f"{_base(new_org['id'])}/standards/{new_standard_b['id']}/versions/{new_version_b['id']}/requirements",
        headers=auth_headers(admin_token),
    ).json()
    new_other_requirement = next(r for r in new_requirements_b if r["reference"] == "9.9")

    new_mappings = client.get(
        f"{_base(new_org['id'])}/requirement-mappings", headers=auth_headers(admin_token)
    ).json()
    assert len(new_mappings) == 1
    new_mapping = new_mappings[0]
    assert new_mapping["from_requirement_id"] == new_child["id"]
    assert new_mapping["to_requirement_id"] == new_other_requirement["id"]
    assert new_mapping["notes"] == "Same underlying obligation"

    new_relationship_types = client.get(
        f"{_base(new_org['id'])}/mapping-relationship-types", headers=auth_headers(admin_token)
    ).json()
    new_relationship_type = next(t for t in new_relationship_types if t["name"] == "Equivalent")
    assert new_relationship_type["implies_equivalence"] is True
    assert new_mapping["relationship_type_id"] == new_relationship_type["id"]


# --- Merging into an *existing* organisation (`ModuleOrgBundleHooks.compute_merge_conflicts`) ---


def test_org_merge_with_no_conflict_adds_the_compliance_standard(client, admin_token):
    """`POST /orgs/{id}/import/merge` (as opposed to the always-fresh-org
    `POST /orgs/import` the round-trip test above exercises) folds a
    bundle's compliance content into an *existing* organisation via
    `ModuleOrgBundleHooks`/`export.py::import_org_data` — this path had no
    test coverage of its own before this one, unlike the core project/
    report-template merge conflicts `test_org_import_merge.py` already
    covers."""
    source_org, source_token = create_org_admin_in(client, admin_token, "Compliance Merge Source")
    standard = _create_standard(client, source_token, source_org["id"], reference="MERGE-STD-A", name="Merge Standard A")
    _create_version(client, source_token, source_org["id"], standard["id"], version_label="1.0")
    bundle_bytes = client.get(f"/api/v1/orgs/{source_org['id']}/export", headers=auth_headers(source_token)).content

    target_org, target_token = create_org_admin_in(client, admin_token, "Compliance Merge Target Clean")
    conflicts = _merge_preview(client, target_token, target_org["id"], bundle_bytes)
    assert conflicts == []

    merge_resp = _merge(client, target_token, target_org["id"], bundle_bytes, resolutions={})
    assert merge_resp.status_code == 200, merge_resp.text
    body = merge_resp.json()
    assert body["compliance_standards_imported"] == 1
    assert body["compliance_standards_skipped"] == 0

    target_standards = client.get(f"{_base(target_org['id'])}/standards", headers=auth_headers(target_token)).json()
    assert any(s["reference"] == "MERGE-STD-A" for s in target_standards)


def test_org_merge_compliance_standard_reference_conflict_can_be_skipped_or_imported_as_a_copy(client, admin_token):
    """Mirrors `test_org_import_merge.py::test_merge_project_name_conflict_
    can_be_skipped_or_imported_as_a_copy`'s exact shape for a compliance
    standard `reference` collision (`export.py::compute_org_merge_
    conflicts`) — the target's existing standard is left alone on `skip`,
    and the bundle's own standard is added as a second, distinct row on
    `import_as_copy` rather than overwriting it (`ORG_MERGE_RESOLUTION_
    CHOICES = {"compliance_standard": {"skip", "import_as_copy"}}`)."""
    source_org, source_token = create_org_admin_in(client, admin_token, "Compliance Merge Conflict Source")
    _create_standard(client, source_token, source_org["id"], reference="MERGE-STD-B", name="Shared Reference Standard")
    bundle_bytes = client.get(f"/api/v1/orgs/{source_org['id']}/export", headers=auth_headers(source_token)).content

    target_org, target_token = create_org_admin_in(client, admin_token, "Compliance Merge Conflict Target")
    existing = _create_standard(client, target_token, target_org["id"], reference="MERGE-STD-B", name="Pre-existing Standard")

    conflicts = _merge_preview(client, target_token, target_org["id"], bundle_bytes)
    standard_conflicts = [c for c in conflicts if c["kind"] == "compliance_standard"]
    assert len(standard_conflicts) == 1
    conflict = standard_conflicts[0]
    assert conflict["name"] == "MERGE-STD-B"
    assert conflict["existing_id"] == existing["id"]

    # Skip: the target's existing standard is untouched, nothing new added.
    skip_resp = _merge(client, target_token, target_org["id"], bundle_bytes, resolutions={conflict["id"]: "skip"})
    assert skip_resp.status_code == 200, skip_resp.text
    assert skip_resp.json()["compliance_standards_imported"] == 0
    assert skip_resp.json()["compliance_standards_skipped"] == 1
    standards_after_skip = client.get(f"{_base(target_org['id'])}/standards", headers=auth_headers(target_token)).json()
    assert len([s for s in standards_after_skip if s["reference"] == "MERGE-STD-B"]) == 1
    assert next(s for s in standards_after_skip if s["reference"] == "MERGE-STD-B")["name"] == "Pre-existing Standard"

    # Import as copy: the bundle's standard is added alongside the existing
    # one, under a renamed reference (mirrors `export.py::_import_compliance_
    # standards`'s "{reference} (imported)" convention — the project-name
    # conflict's exact pattern, applied to a standard's `reference` instead
    # of a project's `name`).
    copy_resp = _merge(client, target_token, target_org["id"], bundle_bytes, resolutions={conflict["id"]: "import_as_copy"})
    assert copy_resp.status_code == 200, copy_resp.text
    assert copy_resp.json()["compliance_standards_imported"] == 1
    standards_after_copy = client.get(f"{_base(target_org['id'])}/standards", headers=auth_headers(target_token)).json()
    assert len([s for s in standards_after_copy if s["reference"] == "MERGE-STD-B"]) == 1
    imported_copy = next(s for s in standards_after_copy if s["reference"] == "MERGE-STD-B (imported)")
    assert imported_copy["name"] == "Shared Reference Standard"


def test_org_merge_rejects_an_invalid_compliance_standard_resolution_value(client, admin_token):
    """`org_export.merge_org_bundle` validates every conflict's resolution
    against `_resolution_choices_by_kind` (core kinds merged with every
    module's own `merge_resolution_choices`) *before* any hook's `import_`
    runs — an unrecognised value for a `compliance_standard` conflict must
    400, the same as an invalid value for a core `project`/`report_
    template` conflict already does (`test_org_import_merge.py::test_merge_
    rejects_an_invalid_resolution_value`)."""
    source_org, source_token = create_org_admin_in(client, admin_token, "Compliance Merge Invalid Resolution Source")
    _create_standard(client, source_token, source_org["id"], reference="MERGE-STD-C", name="Standard C")
    bundle_bytes = client.get(f"/api/v1/orgs/{source_org['id']}/export", headers=auth_headers(source_token)).content

    target_org, target_token = create_org_admin_in(client, admin_token, "Compliance Merge Invalid Resolution Target")
    _create_standard(client, target_token, target_org["id"], reference="MERGE-STD-C", name="Existing Standard C")

    conflicts = _merge_preview(client, target_token, target_org["id"], bundle_bytes)
    conflict = next(c for c in conflicts if c["kind"] == "compliance_standard")

    resp = _merge(client, target_token, target_org["id"], bundle_bytes, resolutions={conflict["id"]: "overwrite"})
    assert resp.status_code == 400, resp.text
