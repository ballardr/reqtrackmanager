"""Tests for the Compliance Module's Phase 9 Approval / Sign-off Workflow
(docs/compliance-module-plan.md Phase 9; docs/Compliance_Module_
Requirements.md §12, §16, §27): the `submit-for-approval`/`approve`/
`reject` state-machine actions, the automatic transitions triggered by a
fresh assessment (`update_requirement_assessment`), an applicability change
(`update_requirement_applicability`), and a material evidence change
(`archive_evidence`/`revalidate_evidence`), the `pending-approvals`
cross-assignment listing, the compliance_officer/PROJECT_MANAGER RBAC
composition, and that the workflow's own history is fully covered by the
existing `get_requirement_history` endpoint (no bespoke history mechanism).

Reuses `test_compliance_standards_api.py`'s and `test_project_compliance_
api.py`'s helpers for setup, the same way `test_compliance_evidence_api.py`
already does — this file's own job starts once a project has a materialised,
assessable requirement.
"""

from __future__ import annotations

from app.modules.compliance.tests.test_compliance_evidence_api import _create_evidence
from app.modules.compliance.tests.test_project_compliance_api import (
    _assign_project_role,
    _assign_standard_to_project,
    _grant_compliance_officer,
    _project_base,
    _setup_published_standard_with_tree,
)
from tests.conftest import auth_headers, create_org_user, create_project, login


def _setup_assessed_pcr(client, admin_token, org_id, *, project_name="Approval Project", status="compliant", tree=None):
    """Standard -> published version -> project assignment -> one
    requirement assessed to `status` (default "compliant", `approval_state`
    left at "assessed" by that assessment call). `tree` lets a caller
    needing more than one project reuse a single `_setup_published_
    standard_with_tree` call, mirroring `test_compliance_evidence_api.py`'s
    own established pattern — calling that helper twice in the same org
    collides on its hardcoded, org-unique `reference`/action-type name.
    Returns (project, assignment, pcr_id, tree)."""
    if tree is None:
        tree = _setup_published_standard_with_tree(client, admin_token, org_id)
    standard, version, _parent, _child, _pa, _ca = tree
    project = create_project(client, admin_token, org_id, name=project_name)
    assignment = _assign_standard_to_project(client, admin_token, org_id, project["id"], standard["id"], version["id"])
    pcr_id = client.get(
        f"{_project_base(project['id'])}/project-compliance/{assignment['id']}/requirements",
        headers=auth_headers(admin_token),
    ).json()[0]["id"]
    resp = client.patch(
        f"{_project_base(project['id'])}/project-compliance/{assignment['id']}/requirements/{pcr_id}/assessment",
        json={"compliance_status": status, "justification": "", "notes": ""},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["approval_state"] == "assessed"
    return project, assignment, pcr_id, tree


def _pcr_path(project_id, assignment_id, pcr_id, suffix=""):
    return f"{_project_base(project_id)}/project-compliance/{assignment_id}/requirements/{pcr_id}{suffix}"


# --- Happy path: assessed -> pending_approval -> approved -------------------------


def test_submit_approve_happy_path(client, admin_token, org_id):
    project, assignment, pcr_id, _tree = _setup_assessed_pcr(client, admin_token, org_id)

    submitted = client.post(
        _pcr_path(project["id"], assignment["id"], pcr_id, "/submit-for-approval"), headers=auth_headers(admin_token)
    )
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["approval_state"] == "pending_approval"

    approved = client.post(
        _pcr_path(project["id"], assignment["id"], pcr_id, "/approve"),
        json={"decision_note": "Reviewed the thermal test certificate; compliant."},
        headers=auth_headers(admin_token),
    )
    assert approved.status_code == 200, approved.text
    body = approved.json()
    assert body["approval_state"] == "approved"
    assert body["approval_decided_at"] is not None
    assert body["approval_decided_by"] is not None
    assert body["decision_note"] == "Reviewed the thermal test certificate; compliant."

    # §12: the approval/sign-off history is the same audit trail as every
    # other compliance history — no separate endpoint or table.
    history = client.get(
        _pcr_path(project["id"], assignment["id"], pcr_id, "/history"), headers=auth_headers(admin_token)
    ).json()
    actions = [e["action"] for e in history]
    assert actions == ["assessed", "submitted_for_approval", "approved"]


def test_reject_requires_decision_note_and_records_it(client, admin_token, org_id):
    project, assignment, pcr_id, _tree = _setup_assessed_pcr(client, admin_token, org_id)
    client.post(_pcr_path(project["id"], assignment["id"], pcr_id, "/submit-for-approval"), headers=auth_headers(admin_token))

    no_note = client.post(
        _pcr_path(project["id"], assignment["id"], pcr_id, "/reject"),
        json={"decision_note": ""}, headers=auth_headers(admin_token),
    )
    assert no_note.status_code == 400

    rejected = client.post(
        _pcr_path(project["id"], assignment["id"], pcr_id, "/reject"),
        json={"decision_note": "Certificate does not cover this configuration."},
        headers=auth_headers(admin_token),
    )
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["approval_state"] == "rejected"
    assert rejected.json()["decision_note"] == "Certificate does not cover this configuration."


# --- State-machine ordering ---------------------------------------------------------


def test_state_machine_ordering_is_enforced(client, admin_token, org_id):
    project, assignment, pcr_id, tree = _setup_assessed_pcr(client, admin_token, org_id)

    # Cannot approve/reject before submitting.
    assert client.post(
        _pcr_path(project["id"], assignment["id"], pcr_id, "/approve"), json={}, headers=auth_headers(admin_token)
    ).status_code == 409
    assert client.post(
        _pcr_path(project["id"], assignment["id"], pcr_id, "/reject"),
        json={"decision_note": "x"}, headers=auth_headers(admin_token),
    ).status_code == 409

    # A never-assessed requirement cannot be submitted for approval either
    # (a second project assigned the *same* standard/version — see
    # `_setup_assessed_pcr`'s own docstring for why a second, independent
    # `_setup_published_standard_with_tree` call would collide instead).
    standard, version, _p, _c, _pa, _ca = tree
    other_project = create_project(client, admin_token, org_id, name="Never Assessed Project")
    other_assignment = _assign_standard_to_project(
        client, admin_token, org_id, other_project["id"], standard["id"], version["id"]
    )
    other_pcr_id = client.get(
        f"{_project_base(other_project['id'])}/project-compliance/{other_assignment['id']}/requirements",
        headers=auth_headers(admin_token),
    ).json()[0]["id"]
    not_assessed_submit = client.post(
        _pcr_path(other_project["id"], other_assignment["id"], other_pcr_id, "/submit-for-approval"),
        headers=auth_headers(admin_token),
    )
    assert not_assessed_submit.status_code == 409

    # Once pending, submitting again 409s (already in flight).
    client.post(_pcr_path(project["id"], assignment["id"], pcr_id, "/submit-for-approval"), headers=auth_headers(admin_token))
    resubmit = client.post(
        _pcr_path(project["id"], assignment["id"], pcr_id, "/submit-for-approval"), headers=auth_headers(admin_token)
    )
    assert resubmit.status_code == 409


# --- Automatic invalidation (§12, §16, §27) -----------------------------------------


def test_reassessing_an_approved_requirement_resets_to_assessed(client, admin_token, org_id):
    """§12: a fresh assessment on an APPROVED row must not leave it silently
    "Approved" — it becomes "assessed" (a new approval cycle is required),
    not "requires_reassessment" (that state is reserved for a material
    change *without* an accompanying reassessment — see service.py)."""
    project, assignment, pcr_id, _tree = _setup_assessed_pcr(client, admin_token, org_id)
    client.post(_pcr_path(project["id"], assignment["id"], pcr_id, "/submit-for-approval"), headers=auth_headers(admin_token))
    client.post(
        _pcr_path(project["id"], assignment["id"], pcr_id, "/approve"), json={}, headers=auth_headers(admin_token)
    )

    reassessed = client.patch(
        _pcr_path(project["id"], assignment["id"], pcr_id, "/assessment"),
        json={"compliance_status": "in_progress", "justification": "", "notes": "Re-checking after a design change."},
        headers=auth_headers(admin_token),
    )
    assert reassessed.status_code == 200, reassessed.text
    assert reassessed.json()["approval_state"] == "assessed"


def test_applicability_change_on_approved_requirement_requires_reassessment(client, admin_token, org_id):
    project, assignment, pcr_id, _tree = _setup_assessed_pcr(client, admin_token, org_id)
    client.post(_pcr_path(project["id"], assignment["id"], pcr_id, "/submit-for-approval"), headers=auth_headers(admin_token))
    client.post(
        _pcr_path(project["id"], assignment["id"], pcr_id, "/approve"), json={}, headers=auth_headers(admin_token)
    )

    changed = client.patch(
        _pcr_path(project["id"], assignment["id"], pcr_id, "/applicability"),
        json={"applicability": "not_applicable", "justification": "Requirement superseded by a design change."},
        headers=auth_headers(admin_token),
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["approval_state"] == "requires_reassessment"

    history_actions = [
        e["action"]
        for e in client.get(
            _pcr_path(project["id"], assignment["id"], pcr_id, "/history"), headers=auth_headers(admin_token)
        ).json()
    ]
    assert "applicability_changed" in history_actions


def test_archiving_linked_evidence_invalidates_an_approved_requirement(client, admin_token, org_id):
    project, assignment, pcr_id, _tree = _setup_assessed_pcr(client, admin_token, org_id)
    evidence = _create_evidence(
        client, admin_token, project["id"], project_compliance_requirement_ids=[pcr_id],
    )
    client.post(_pcr_path(project["id"], assignment["id"], pcr_id, "/submit-for-approval"), headers=auth_headers(admin_token))
    client.post(
        _pcr_path(project["id"], assignment["id"], pcr_id, "/approve"), json={}, headers=auth_headers(admin_token)
    )

    archived = client.post(
        f"{_project_base(project['id'])}/evidence/{evidence['id']}/archive", headers=auth_headers(admin_token)
    )
    assert archived.status_code == 200, archived.text

    pcr = client.get(_pcr_path(project["id"], assignment["id"], pcr_id), headers=auth_headers(admin_token)).json()
    assert pcr["approval_state"] == "requires_reassessment"

    history_actions = [
        e["action"]
        for e in client.get(
            _pcr_path(project["id"], assignment["id"], pcr_id, "/history"), headers=auth_headers(admin_token)
        ).json()
    ]
    assert "approval_invalidated" in history_actions


def test_revalidating_linked_evidence_invalidates_a_pending_approval(client, admin_token, org_id):
    project, assignment, pcr_id, _tree = _setup_assessed_pcr(client, admin_token, org_id)
    evidence = _create_evidence(
        client, admin_token, project["id"], project_compliance_requirement_ids=[pcr_id], expiry_date="2027-01-01",
    )
    client.post(_pcr_path(project["id"], assignment["id"], pcr_id, "/submit-for-approval"), headers=auth_headers(admin_token))

    revalidated = client.post(
        f"{_project_base(project['id'])}/evidence/{evidence['id']}/revalidate",
        json={"new_expiry_date": "2028-01-01", "justification": "Annual recertification."},
        headers=auth_headers(admin_token),
    )
    assert revalidated.status_code == 200, revalidated.text

    pcr = client.get(_pcr_path(project["id"], assignment["id"], pcr_id), headers=auth_headers(admin_token)).json()
    assert pcr["approval_state"] == "requires_reassessment"


# --- pending-approvals listing (compliance_list_pending_approvals MCP tool) --------


def test_pending_approvals_listing(client, admin_token, org_id):
    project, assignment, pcr_id, _tree = _setup_assessed_pcr(client, admin_token, org_id)

    empty = client.get(f"{_project_base(project['id'])}/pending-approvals", headers=auth_headers(admin_token))
    assert empty.status_code == 200
    assert empty.json() == []

    client.post(_pcr_path(project["id"], assignment["id"], pcr_id, "/submit-for-approval"), headers=auth_headers(admin_token))
    pending = client.get(f"{_project_base(project['id'])}/pending-approvals", headers=auth_headers(admin_token))
    assert pending.status_code == 200, pending.text
    assert len(pending.json()) == 1
    assert pending.json()[0]["project_compliance_requirement_id"] == pcr_id

    client.post(
        _pcr_path(project["id"], assignment["id"], pcr_id, "/approve"), json={}, headers=auth_headers(admin_token)
    )
    after_approval = client.get(f"{_project_base(project['id'])}/pending-approvals", headers=auth_headers(admin_token))
    assert after_approval.json() == []


# --- RBAC composition (§11, §26) -----------------------------------------------------


def test_rbac_officer_grant_manager_override_and_member_forbidden_for_approval_actions(client, admin_token, org_id):
    project, assignment, pcr_id, _tree = _setup_assessed_pcr(client, admin_token, org_id)

    plain_member_id = create_org_user(client, admin_token, org_id, "approval.plain@example.com", role="member")
    officer_id = create_org_user(client, admin_token, org_id, "approval.officer@example.com", role="member")
    manager_id = create_org_user(client, admin_token, org_id, "approval.pm@example.com", role="member")

    _assign_project_role(client, admin_token, project["id"], plain_member_id, "stakeholder")
    _assign_project_role(client, admin_token, project["id"], officer_id, "stakeholder")
    _grant_compliance_officer(client, admin_token, project["id"], officer_id)
    _assign_project_role(client, admin_token, project["id"], manager_id, "project_manager")

    plain_token = login(client, "approval.plain@example.com", "Password123!")
    officer_token = login(client, "approval.officer@example.com", "Password123!")
    manager_token = login(client, "approval.pm@example.com", "Password123!")

    def _submit(token):
        return client.post(
            _pcr_path(project["id"], assignment["id"], pcr_id, "/submit-for-approval"), headers=auth_headers(token)
        )

    assert _submit(plain_token).status_code == 403
    # Read access (the pending-approvals listing) stays open to any project member.
    assert client.get(
        f"{_project_base(project['id'])}/pending-approvals", headers=auth_headers(plain_token)
    ).status_code == 200

    assert _submit(officer_token).status_code == 200
    assert client.post(
        _pcr_path(project["id"], assignment["id"], pcr_id, "/approve"), json={}, headers=auth_headers(manager_token)
    ).status_code == 200
