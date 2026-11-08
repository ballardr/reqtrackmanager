"""A project created from a template receives the template's compliance assignments, assessments and evidence.

Assessment content (applicability, status, notes, required-action work) and evidence travel; every approval is
returned to `assessed` with no decision or decider, and evidence has no revalidation history.
"""

from __future__ import annotations

from datetime import date, timedelta

from app.modules.compliance.tests.test_compliance_export_import import _find_pcr
from app.modules.compliance.tests.test_project_compliance_api import (
    _assign_standard_to_project,
    _project_base,
    _setup_published_standard_with_tree,
)
from tests.conftest import auth_headers, create_project

TODAY = date.today()


def test_a_template_clone_copies_assignments_assessments_and_evidence_without_approvals(client, admin_token, org_id):
    standard, version, _parent, child, _pa, _child_action = _setup_published_standard_with_tree(client, admin_token, org_id)
    h = auth_headers(admin_token)
    template = create_project(client, admin_token, org_id, name="Compliance Template Source")
    assignment = _assign_standard_to_project(client, admin_token, org_id, template["id"], standard["id"], version["id"])
    pcr = _find_pcr(client, admin_token, template["id"], assignment["id"], child["id"])
    base = _project_base(template["id"])
    assert client.patch(
        f"{base}/project-compliance/{assignment['id']}/requirements/{pcr['id']}/assessment",
        json={"compliance_status": "compliant", "notes": "Thermal test passed"}, headers=h,
    ).status_code == 200
    evidence = client.post(f"{base}/evidence", json={
        "title": "Thermal Test Certificate", "issued_date": str(TODAY), "expiry_date": str(TODAY + timedelta(days=300)),
        "project_compliance_requirement_ids": [pcr["id"]],
    }, headers=h)
    assert evidence.status_code == 201, evidence.text
    assert client.post(
        f"{base}/evidence/{evidence.json()['id']}/revalidate",
        json={"new_expiry_date": str(TODAY + timedelta(days=700)), "justification": "Retested"}, headers=h,
    ).status_code == 200
    assert client.patch(f"/api/v1/projects/{template['id']}", json={"is_template": True}, headers=h).status_code == 200

    created = client.post(
        "/api/v1/projects",
        json={"organization_id": org_id, "name": "Compliance From Template", "summary": "", "template_project_id": template["id"]},
        headers=h,
    )
    assert created.status_code == 201, created.text
    new_id = created.json()["id"]

    assignments = client.get(f"{_project_base(new_id)}/project-compliance", headers=h).json()
    assert [a["standard_version_id"] for a in assignments] == [version["id"]]
    new_pcr = _find_pcr(client, admin_token, new_id, assignments[0]["id"], child["id"])
    assert new_pcr["compliance_status"] == "compliant" and new_pcr["notes"] == "Thermal test passed"
    assert new_pcr["approval_state"] in ("not_assessed", "assessed")
    copied = client.get(f"{_project_base(new_id)}/evidence", headers=h).json()
    assert [e["title"] for e in copied] == ["Thermal Test Certificate"]
    assert len(copied[0]["linked_requirement_ids"]) == 1
    assert client.get(f"{_project_base(new_id)}/evidence/{copied[0]['id']}/revalidations", headers=h).json() == []
