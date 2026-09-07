"""Tests for the Compliance Module's Phase 14 Org Compliance View +
Dashboard backend surface (docs/compliance-module-plan.md Phase 14;
docs/Compliance_Module_Requirements.md §22, §23): the five org-wide
cross-assignment aggregation endpoints on the org router
(`non-compliant-requirements`, `pending-approvals`,
`outstanding-required-actions`, `expiring-evidence`, `reviews-due`) plus
`recent-activity`, and the new project-level `outstanding-required-actions`
endpoint these org endpoints are built on top of.

Reuses `test_compliance_standards_api.py`'s and `test_project_compliance_
api.py`'s helpers for setup, and `test_compliance_evidence_api.py`'s
`_create_evidence`, the same way `test_compliance_reviews_and_
notifications.py` already does — this file's own job starts once two
projects have real, differently-shaped compliance data to aggregate across.
"""

from __future__ import annotations

from datetime import date, timedelta

from app.modules.compliance.tests.test_compliance_evidence_api import _create_evidence
from app.modules.compliance.tests.test_compliance_standards_api import _base, _grant_compliance_manager
from app.modules.compliance.tests.test_project_compliance_api import (
    _assign_standard_to_project,
    _project_base,
    _setup_published_standard_with_tree,
)
from tests.conftest import auth_headers, create_org_user, create_project, login

TODAY = date.today()


def _pcr_for(client, token, project_id, assignment_id, requirement_id):
    pcrs = client.get(
        f"{_project_base(project_id)}/project-compliance/{assignment_id}/requirements", headers=auth_headers(token)
    ).json()
    return next(p for p in pcrs if p["requirement_id"] == requirement_id)


def _setup_two_projects(client, admin_token, org_id):
    """One published standard assigned to two projects — Project A gets a
    Non-Compliant requirement, a Pending-Approval requirement, expired
    evidence, and an overdue review; Project B is left at its freshly-
    assigned defaults (every required action assessment starts incomplete
    on both — see this module's own materialisation design — so both
    projects contribute to `outstanding-required-actions` with no extra
    setup needed). Returns (standard, project_a, project_b, assignment_a,
    child, parent)."""
    standard, version, parent, child, _parent_action, _child_action = _setup_published_standard_with_tree(
        client, admin_token, org_id
    )
    project_a = create_project(client, admin_token, org_id, name="Org Dashboard Project A")
    project_b = create_project(client, admin_token, org_id, name="Org Dashboard Project B")
    assignment_a = _assign_standard_to_project(
        client, admin_token, org_id, project_a["id"], standard["id"], version["id"]
    )
    _assign_standard_to_project(client, admin_token, org_id, project_b["id"], standard["id"], version["id"])

    child_pcr = _pcr_for(client, admin_token, project_a["id"], assignment_a["id"], child["id"])
    parent_pcr = _pcr_for(client, admin_token, project_a["id"], assignment_a["id"], parent["id"])

    non_compliant = client.patch(
        f"{_project_base(project_a['id'])}/project-compliance/{assignment_a['id']}/requirements/{child_pcr['id']}/assessment",
        json={"compliance_status": "non_compliant", "justification": "Failed thermal test."},
        headers=auth_headers(admin_token),
    )
    assert non_compliant.status_code == 200, non_compliant.text

    assessed_compliant = client.patch(
        f"{_project_base(project_a['id'])}/project-compliance/{assignment_a['id']}/requirements/{parent_pcr['id']}/assessment",
        json={"compliance_status": "compliant"},
        headers=auth_headers(admin_token),
    )
    assert assessed_compliant.status_code == 200, assessed_compliant.text
    submitted = client.post(
        f"{_project_base(project_a['id'])}/project-compliance/{assignment_a['id']}/requirements/{parent_pcr['id']}/submit-for-approval",
        headers=auth_headers(admin_token),
    )
    assert submitted.status_code == 200, submitted.text

    _create_evidence(client, admin_token, project_a["id"], expiry_date=(TODAY - timedelta(days=5)).isoformat())

    review = client.post(
        f"{_project_base(project_a['id'])}/project-compliance/{assignment_a['id']}/reviews",
        json={"frequency_label": "Annual", "next_due_date": (TODAY - timedelta(days=1)).isoformat()},
        headers=auth_headers(admin_token),
    )
    assert review.status_code == 201, review.text

    return standard, project_a, project_b, assignment_a, child, parent


# --- Non-compliant requirements (org-wide) ---------------------------------------


def test_org_non_compliant_requirements_aggregates_across_projects(client, admin_token, org_id):
    _standard, project_a, _project_b, _assignment_a, child, _parent = _setup_two_projects(client, admin_token, org_id)

    resp = client.get(f"{_base(org_id)}/non-compliant-requirements", headers=auth_headers(admin_token))
    assert resp.status_code == 200, resp.text
    rows = resp.json()
    assert len(rows) == 1
    assert rows[0]["project_id"] == project_a["id"]
    assert rows[0]["project_name"] == project_a["name"]
    assert rows[0]["requirement_id"] == child["id"]
    assert rows[0]["justification"] == "Failed thermal test."


# --- Pending approvals (org-wide) -------------------------------------------------


def test_org_pending_approvals_aggregates_across_projects(client, admin_token, org_id):
    _standard, project_a, _project_b, _assignment_a, _child, parent = _setup_two_projects(client, admin_token, org_id)

    resp = client.get(f"{_base(org_id)}/pending-approvals", headers=auth_headers(admin_token))
    assert resp.status_code == 200, resp.text
    rows = resp.json()
    assert len(rows) == 1
    assert rows[0]["project_id"] == project_a["id"]
    assert rows[0]["project_name"] == project_a["name"]
    assert rows[0]["requirement_id"] == parent["id"]


# --- Outstanding required actions (org-wide + project-level) --------------------


def test_org_outstanding_required_actions_covers_every_project(client, admin_token, org_id):
    """Every `ComplianceRequiredActionAssessment` starts incomplete on
    materialisation (Phase 7's own design) — so both Project A and Project
    B, despite very different assessment states, each contribute their own
    (still-incomplete) parent+child required actions with zero extra setup,
    proving this is a genuine per-project aggregation rather than an
    accidental single-project count."""
    _standard, project_a, project_b, assignment_a, _child, _parent = _setup_two_projects(client, admin_token, org_id)

    org_resp = client.get(f"{_base(org_id)}/outstanding-required-actions", headers=auth_headers(admin_token))
    assert org_resp.status_code == 200, org_resp.text
    org_rows = org_resp.json()
    assert len(org_rows) == 4
    by_project: dict[str, int] = {}
    for row in org_rows:
        by_project[row["project_id"]] = by_project.get(row["project_id"], 0) + 1
    assert by_project == {project_a["id"]: 2, project_b["id"]: 2}
    assert all(row["project_name"] in (project_a["name"], project_b["name"]) for row in org_rows)

    # Project-level listing (new in Phase 14, alongside the org one above)
    # returns just that project's own two rows.
    project_resp = client.get(
        f"{_project_base(project_a['id'])}/outstanding-required-actions", headers=auth_headers(admin_token)
    )
    assert project_resp.status_code == 200, project_resp.text
    project_rows = project_resp.json()
    assert len(project_rows) == 2
    assert all(row["project_id"] == project_a["id"] for row in project_rows)
    assert {row["required_action_name"] for row in project_rows} == {"Section review", "Run thermal test"}

    # Once a required action is completed it drops off both listings.
    assessment_id = project_rows[0]["required_action_assessment_id"]
    pcr_id = project_rows[0]["project_compliance_requirement_id"]
    complete = client.post(
        f"{_project_base(project_a['id'])}/project-compliance/{assignment_a['id']}/requirements/{pcr_id}"
        f"/required-action-assessments/{assessment_id}/complete",
        headers=auth_headers(admin_token),
    )
    assert complete.status_code == 200, complete.text
    after = client.get(
        f"{_project_base(project_a['id'])}/outstanding-required-actions", headers=auth_headers(admin_token)
    ).json()
    assert len(after) == 1


# --- Expiring evidence (org-wide) -------------------------------------------------


def test_org_expiring_evidence_aggregates_across_projects(client, admin_token, org_id):
    _standard, project_a, _project_b, _assignment_a, _child, _parent = _setup_two_projects(client, admin_token, org_id)

    resp = client.get(f"{_base(org_id)}/expiring-evidence", headers=auth_headers(admin_token))
    assert resp.status_code == 200, resp.text
    rows = resp.json()
    assert len(rows) == 1
    assert rows[0]["project_id"] == project_a["id"]
    assert rows[0]["project_name"] == project_a["name"]
    assert rows[0]["validity_state"] == "expired"


# --- Reviews due (org-wide, incl. include_upcoming) -------------------------------


def test_org_reviews_due_respects_include_upcoming(client, admin_token, org_id):
    standard, project_a, project_b, assignment_a, _child, _parent = _setup_two_projects(client, admin_token, org_id)

    # An "upcoming" (not yet due/overdue) standard-level review, which
    # `list_reviews_due_for_project` deliberately excludes by default.
    upcoming = client.post(
        f"{_base(org_id)}/standards/{standard['id']}/reviews",
        json={"frequency_label": "Annual audit", "next_due_date": (TODAY + timedelta(days=200)).isoformat()},
        headers=auth_headers(admin_token),
    )
    assert upcoming.status_code == 201, upcoming.text

    default_resp = client.get(f"{_base(org_id)}/reviews-due", headers=auth_headers(admin_token))
    assert default_resp.status_code == 200, default_resp.text
    default_rows = default_resp.json()
    assert len(default_rows) == 1
    assert default_rows[0]["project_id"] == project_a["id"]
    assert default_rows[0]["review"]["schedule_state"] == "overdue"

    upcoming_resp = client.get(
        f"{_base(org_id)}/reviews-due?include_upcoming=true", headers=auth_headers(admin_token)
    )
    assert upcoming_resp.status_code == 200, upcoming_resp.text
    upcoming_rows = upcoming_resp.json()
    # The overdue project-level review (Project A) plus the upcoming
    # standard-level review, once per project it's assigned to (both A
    # and B are assigned this standard).
    assert len(upcoming_rows) == 3
    schedule_states = sorted(row["review"]["schedule_state"] for row in upcoming_rows)
    assert schedule_states == ["overdue", "upcoming", "upcoming"]
    upcoming_project_ids = {row["project_id"] for row in upcoming_rows if row["review"]["schedule_state"] == "upcoming"}
    assert upcoming_project_ids == {project_a["id"], project_b["id"]}


# --- Recent activity (org-wide) ---------------------------------------------------


def test_org_recent_activity_lists_assessment_changes(client, admin_token, org_id):
    _standard, project_a, _project_b, _assignment_a, child, parent = _setup_two_projects(client, admin_token, org_id)

    resp = client.get(f"{_base(org_id)}/recent-activity", headers=auth_headers(admin_token))
    assert resp.status_code == 200, resp.text
    rows = resp.json()
    actions = {row["action"] for row in rows}
    assert "assessed" in actions
    assert "submitted_for_approval" in actions
    assert all(row["project_id"] == project_a["id"] for row in rows)
    requirement_names = {row["requirement_name"] for row in rows}
    assert requirement_names == {child["name"], parent["name"]}

    limited = client.get(f"{_base(org_id)}/recent-activity?limit=1", headers=auth_headers(admin_token))
    assert limited.status_code == 200
    assert len(limited.json()) == 1


# --- RBAC: manage-gated, not view-gated (§26) -------------------------------------


def test_org_dashboard_endpoints_require_compliance_manager(client, admin_token, org_id):
    """§26 lists "View compliance across projects" specifically under
    Compliance Manager — a plain org member is forbidden from every Phase
    14 org-wide endpoint, mirroring `list_all_project_compliance`'s own
    existing RBAC (confirmed unaffected by this phase); a direct
    `compliance_manager` grant (no org_admin) is sufficient, matching
    `require_module_role`'s existing composition."""
    _setup_two_projects(client, admin_token, org_id)

    plain_id = create_org_user(client, admin_token, org_id, "plain.viewer@example.com", role="member")
    plain_token = login(client, "plain.viewer@example.com", "Password123!")

    manager_id = create_org_user(client, admin_token, org_id, "dashboard.manager@example.com", role="member")
    _grant_compliance_manager(client, admin_token, org_id, manager_id)
    manager_token = login(client, "dashboard.manager@example.com", "Password123!")

    endpoints = [
        "non-compliant-requirements",
        "pending-approvals",
        "outstanding-required-actions",
        "expiring-evidence",
        "reviews-due",
        "recent-activity",
    ]
    for endpoint in endpoints:
        forbidden = client.get(f"{_base(org_id)}/{endpoint}", headers=auth_headers(plain_token))
        assert forbidden.status_code == 403, f"{endpoint}: {forbidden.text}"

        allowed = client.get(f"{_base(org_id)}/{endpoint}", headers=auth_headers(manager_token))
        assert allowed.status_code == 200, f"{endpoint}: {allowed.text}"
    assert plain_id and manager_id
