"""Tests that the Compliance approval of an assessment runs on the core approval engine: the assessment is a gated type for
approval separation (a project or the organisation may require a person other than the assessor to approve) and for
approval policy (a role a policy names may approve and reject), while the default approvers (Compliance Officer, project
manager, administrators) are unchanged and a person who is not admitted is refused with the same message as before."""

from __future__ import annotations

import uuid

from app.modules.compliance.tests.test_compliance_approval_workflow import _pcr_path, _setup_assessed_pcr
from app.modules.compliance.tests.test_project_compliance_api import _assign_project_role, _grant_compliance_officer
from tests.conftest import auth_headers, create_org_user, login

GATE = "project_compliance_requirement"
POLICY = "/api/v1/projects/{project}/modules/traceability/approval-policies/" + GATE


def _person(client, admin_token, org_id, project_id, role="stakeholder", officer=False) -> str:
    email = f"approval.engine.{uuid.uuid4().hex[:8]}@example.com"
    user_id = create_org_user(client, admin_token, org_id, email, role="member")
    _assign_project_role(client, admin_token, project_id, user_id, role)
    if officer:
        _grant_compliance_officer(client, admin_token, project_id, user_id)
    return login(client, email, "Password123!")


def _submit(client, token, project, assignment, pcr_id):
    return client.post(_pcr_path(project["id"], assignment["id"], pcr_id, "/submit-for-approval"), headers=auth_headers(token))


def _decide(client, token, project, assignment, pcr_id, action, note="Checked."):
    return client.post(
        _pcr_path(project["id"], assignment["id"], pcr_id, f"/{action}"), json={"decision_note": note}, headers=auth_headers(token),
    )


def test_the_assessment_is_a_gated_type_in_the_projects_separation_settings(client, admin_token, org_id):
    project, _assignment, _pcr, _tree = _setup_assessed_pcr(client, admin_token, org_id, project_name="Engine Listing Project")
    rows = client.get(f"/api/v1/projects/{project['id']}/approval-separation", headers=auth_headers(admin_token)).json()
    assert GATE in {r["artefact_type"] for r in rows["types"]}


def test_a_required_separate_approver_refuses_the_assessor_and_admits_another_officer(client, admin_token, org_id):
    project, assignment, pcr_id, _tree = _setup_assessed_pcr(client, admin_token, org_id, project_name="Engine Separation Project")
    other = _person(client, admin_token, org_id, project["id"], officer=True)
    assert _submit(client, admin_token, project, assignment, pcr_id).status_code == 200

    set_rule = client.put(
        f"/api/v1/projects/{project['id']}/approval-separation/{GATE}", json={"separate_approver": True}, headers=auth_headers(admin_token),
    )
    assert set_rule.status_code == 200, set_rule.text
    refused = _decide(client, admin_token, project, assignment, pcr_id, "approve")
    assert refused.status_code == 403 and "separate approver" in refused.json()["detail"]
    status = client.get(
        f"/api/v1/projects/{project['id']}/approval-separation/status/{GATE}/{pcr_id}", headers=auth_headers(admin_token),
    )
    assert status.status_code == 200, status.text
    assert _decide(client, other, project, assignment, pcr_id, "approve").status_code == 200


def test_a_rejection_is_not_subject_to_separation(client, admin_token, org_id):
    project, assignment, pcr_id, _tree = _setup_assessed_pcr(client, admin_token, org_id, project_name="Engine Reject Project")
    assert _submit(client, admin_token, project, assignment, pcr_id).status_code == 200
    client.put(
        f"/api/v1/projects/{project['id']}/approval-separation/{GATE}", json={"separate_approver": True}, headers=auth_headers(admin_token),
    )
    assert _decide(client, admin_token, project, assignment, pcr_id, "reject", "Needs more evidence.").status_code == 200


def test_a_person_who_is_not_an_approver_is_refused_as_before(client, admin_token, org_id):
    project, assignment, pcr_id, _tree = _setup_assessed_pcr(client, admin_token, org_id, project_name="Engine Refused Project")
    plain = _person(client, admin_token, org_id, project["id"])
    assert _submit(client, admin_token, project, assignment, pcr_id).status_code == 200
    refused = _decide(client, plain, project, assignment, pcr_id, "approve")
    assert refused.status_code == 403 and refused.json()["detail"] == "Insufficient permissions."
    assert _decide(client, plain, project, assignment, pcr_id, "reject").status_code == 403


def test_a_role_an_approval_policy_names_may_approve_and_reject_assessments(client, admin_token, org_id):
    project, assignment, pcr_id, _tree = _setup_assessed_pcr(client, admin_token, org_id, project_name="Engine Policy Project")
    plain = _person(client, admin_token, org_id, project["id"], role="member")
    assert _submit(client, admin_token, project, assignment, pcr_id).status_code == 200
    enabled = client.put(
        f"/api/v1/orgs/{org_id}/modules/traceability", json={"enabled": True, "default_project_enabled": True}, headers=auth_headers(admin_token),
    )
    assert enabled.status_code == 200, enabled.text

    assert _decide(client, plain, project, assignment, pcr_id, "approve").status_code == 403
    named = client.put(
        POLICY.format(project=project["id"]), json={"roles": [{"kind": "project", "key": "member"}]}, headers=auth_headers(admin_token),
    )
    assert named.status_code == 200, named.text
    assert _decide(client, plain, project, assignment, pcr_id, "approve").status_code == 200
