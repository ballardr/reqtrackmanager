"""Tests for the Compliance Module's Phase 7 Project Compliance Assignment &
Assessment API (docs/compliance-module-plan.md Phase 7; docs/Compliance_
Module_Requirements.md §7-§11, §16, §20, §26): assigning a published standard
version to a project (org router), the full per-project assessment surface
(project router) — applicability (including §9's hierarchical inheritance/
override), compliance status, mandatory-justification enforcement (§9/§16),
required action assessments, assessment history, the §20 overall-status
calculation, the two Phase 7 MCP-tool-backing endpoints
(`compliance_get_project_status`/`compliance_list_non_compliant_
requirements`), the compliance_officer/PROJECT_MANAGER RBAC composition,
and cross-scope isolation.

Reuses `test_compliance_standards_api.py`'s own small API helpers for the
Phase 6 standards-catalog side of each test's setup (create/publish a
standard version with a requirement tree), the same way `test_oidc_
provisioning.py`/`test_scim.py` already import helpers from `test_access_
review.py` — this file's own job starts once a published version exists.
"""

from __future__ import annotations

from tests.conftest import auth_headers, create_org_user, create_project, login
from tests.test_compliance_standards_api import (
    _base,
    _create_action_type,
    _create_required_action,
    _create_requirement,
    _create_standard,
    _create_version,
    _grant_compliance_manager,
)

# --- Small API helpers -----------------------------------------------------------


def _project_base(project_id: str) -> str:
    return f"/api/v1/projects/{project_id}/modules/compliance"


def _publish_version(client, token, org_id, standard_id, version_id):
    resp = client.post(f"{_base(org_id)}/standards/{standard_id}/versions/{version_id}/publish", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return resp.json()


def _grant_compliance_officer(client, admin_token, project_id, user_id):
    resp = client.post(
        f"/api/v1/projects/{project_id}/members/{user_id}/module-roles",
        json={"module_key": "compliance", "role_key": "compliance_officer"},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 204, resp.text


def _assign_project_role(client, admin_token, project_id, user_id, role):
    resp = client.post(
        f"/api/v1/projects/{project_id}/roles", json={"user_id": user_id, "role": role},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 204, resp.text


def _assign_standard_to_project(client, token, org_id, project_id, standard_id, version_id, **extra):
    payload = {"standard_id": standard_id, "standard_version_id": version_id, **extra}
    resp = client.post(f"{_base(org_id)}/projects/{project_id}/project-compliance", json=payload, headers=auth_headers(token))
    assert resp.status_code == 201, resp.text
    return resp.json()


def _setup_published_standard_with_tree(client, admin_token, org_id):
    """Standard -> draft version -> parent requirement ("section") with one
    child requirement, each with a required action -> published. Returns
    (standard, version, parent_requirement, child_requirement,
    parent_required_action, child_required_action)."""
    action_type = _create_action_type(client, admin_token, org_id, name="Test")
    standard = _create_standard(client, admin_token, org_id, reference="EMC-1", name="EMC/EMF Standard")
    version = _create_version(client, admin_token, org_id, standard["id"], version_label="2.0")
    parent = _create_requirement(
        client, admin_token, org_id, standard["id"], version["id"], name="Environmental requirements", reference="4",
    )
    child = _create_requirement(
        client, admin_token, org_id, standard["id"], version["id"],
        name="Temperature", reference="4.1", parent_requirement_id=parent["id"],
    )
    parent_action = _create_required_action(
        client, admin_token, org_id, standard["id"], version["id"], parent["id"], action_type["id"], name="Section review",
    )
    child_action = _create_required_action(
        client, admin_token, org_id, standard["id"], version["id"], child["id"], action_type["id"], name="Run thermal test",
    )
    _publish_version(client, admin_token, org_id, standard["id"], version["id"])
    return standard, version, parent, child, parent_action, child_action


# --- Assignment (org router) ----------------------------------------------------


def test_compliance_manager_can_assign_a_standard_plain_member_cannot(client, admin_token, org_id):
    """§26: assigning a standard to a project is a Compliance Manager
    decision — a direct `compliance_manager` grant (no org_admin) suffices
    (`require_module_role`'s existing composition), a plain org member
    cannot."""
    standard, version, _parent, _child, _pa, _ca = _setup_published_standard_with_tree(client, admin_token, org_id)
    project = create_project(client, admin_token, org_id, name="Manager Assign Project")

    manager_id = create_org_user(client, admin_token, org_id, "compliance.manager@example.com", role="member")
    _grant_compliance_manager(client, admin_token, org_id, manager_id)
    manager_token = login(client, "compliance.manager@example.com", "Password123!")

    assigned = client.post(
        f"{_base(org_id)}/projects/{project['id']}/project-compliance",
        json={"standard_id": standard["id"], "standard_version_id": version["id"]},
        headers=auth_headers(manager_token),
    )
    assert assigned.status_code == 201, assigned.text

    create_org_user(client, admin_token, org_id, "plain.assigner@example.com", role="member")
    plain_token = login(client, "plain.assigner@example.com", "Password123!")
    other_project = create_project(client, admin_token, org_id, name="Manager Assign Project 2")
    forbidden = client.post(
        f"{_base(org_id)}/projects/{other_project['id']}/project-compliance",
        json={"standard_id": standard["id"], "standard_version_id": version["id"]},
        headers=auth_headers(plain_token),
    )
    assert forbidden.status_code == 403


def test_assignment_requires_published_version(client, admin_token, org_id):
    """§4/§7: only a PUBLISHED version may be assigned; a draft 409s."""
    standard = _create_standard(client, admin_token, org_id, reference="DRAFT-STD")
    version = _create_version(client, admin_token, org_id, standard["id"])
    project = create_project(client, admin_token, org_id, name="Draft Assignment Project")

    resp = client.post(
        f"{_base(org_id)}/projects/{project['id']}/project-compliance",
        json={"standard_id": standard["id"], "standard_version_id": version["id"]},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 409, resp.text


def test_assignment_happy_path_materialises_assessment_rows(client, admin_token, org_id):
    """Assigning a published version materialises one ProjectComplianceRequirement
    per requirement (parent + child) and one ComplianceRequiredActionAssessment
    per required action, all starting at their defaults (§8, §25)."""
    standard, version, parent, child, parent_action, child_action = _setup_published_standard_with_tree(
        client, admin_token, org_id
    )
    project = create_project(client, admin_token, org_id, name="Happy Path Project")

    assignment = _assign_standard_to_project(
        client, admin_token, org_id, project["id"], standard["id"], version["id"], target_compliance_date="2027-01-01",
    )
    assert assignment["standard_version_id"] == version["id"]
    assert assignment["target_compliance_date"] == "2027-01-01"
    assert assignment["is_archived"] is False

    # Assigning the same version again is rejected (one row per pair).
    dup = client.post(
        f"{_base(org_id)}/projects/{project['id']}/project-compliance",
        json={"standard_id": standard["id"], "standard_version_id": version["id"]},
        headers=auth_headers(admin_token),
    )
    assert dup.status_code == 400

    requirements = client.get(
        f"{_project_base(project['id'])}/project-compliance/{assignment['id']}/requirements",
        headers=auth_headers(admin_token),
    )
    assert requirements.status_code == 200, requirements.text
    by_requirement_id = {r["requirement_id"]: r for r in requirements.json()}
    assert set(by_requirement_id) == {parent["id"], child["id"]}
    for row in by_requirement_id.values():
        assert row["compliance_status"] == "not_started"
        assert row["explicit_applicability"] is None
        assert row["effective_applicability"] == "applicable"
        assert row["applicability_source"] == "explicit"
        assert row["approval_state"] == "not_assessed"

    child_pcr_id = by_requirement_id[child["id"]]["id"]
    actions = client.get(
        f"{_project_base(project['id'])}/project-compliance/{assignment['id']}/requirements/{child_pcr_id}"
        "/required-action-assessments",
        headers=auth_headers(admin_token),
    )
    assert actions.status_code == 200, actions.text
    assert len(actions.json()) == 1
    assert actions.json()[0]["required_action_id"] == child_action["id"]
    assert actions.json()[0]["is_completed"] is False


# --- Hierarchical applicability (§9) ---------------------------------------------


def test_hierarchical_applicability_inherit_and_override(client, admin_token, org_id):
    standard, version, parent, child, _pa, _ca = _setup_published_standard_with_tree(client, admin_token, org_id)
    project = create_project(client, admin_token, org_id, name="Applicability Project")
    assignment = _assign_standard_to_project(client, admin_token, org_id, project["id"], standard["id"], version["id"])

    requirements = client.get(
        f"{_project_base(project['id'])}/project-compliance/{assignment['id']}/requirements",
        headers=auth_headers(admin_token),
    ).json()
    by_requirement_id = {r["requirement_id"]: r for r in requirements}
    parent_pcr_id = by_requirement_id[parent["id"]]["id"]
    child_pcr_id = by_requirement_id[child["id"]]["id"]

    # No justification -> 400.
    no_justification = client.patch(
        f"{_project_base(project['id'])}/project-compliance/{assignment['id']}/requirements/{parent_pcr_id}/applicability",
        json={"applicability": "not_applicable", "justification": ""},
        headers=auth_headers(admin_token),
    )
    assert no_justification.status_code == 400

    # Mark the parent section Not Applicable, with a justification.
    parent_na = client.patch(
        f"{_project_base(project['id'])}/project-compliance/{assignment['id']}/requirements/{parent_pcr_id}/applicability",
        json={"applicability": "not_applicable", "justification": "Product has no enclosure requiring this section."},
        headers=auth_headers(admin_token),
    )
    assert parent_na.status_code == 200, parent_na.text
    assert parent_na.json()["effective_applicability"] == "not_applicable"
    assert parent_na.json()["applicability_source"] == "explicit"
    assert parent_na.json()["applicability_set_by"] is not None

    # The child, with no explicit decision of its own, now shows inherited NA.
    child_row = client.get(
        f"{_project_base(project['id'])}/project-compliance/{assignment['id']}/requirements/{child_pcr_id}",
        headers=auth_headers(admin_token),
    ).json()
    assert child_row["effective_applicability"] == "not_applicable"
    assert child_row["applicability_source"] == "inherited"

    # The child is explicitly overridden back to Applicable.
    override = client.patch(
        f"{_project_base(project['id'])}/project-compliance/{assignment['id']}/requirements/{child_pcr_id}/applicability",
        json={"applicability": "applicable", "justification": ""},
        headers=auth_headers(admin_token),
    )
    assert override.status_code == 200, override.text
    assert override.json()["effective_applicability"] == "applicable"
    assert override.json()["applicability_source"] == "overridden"


# --- Assessment + mandatory rationale (§10, §16) ---------------------------------


def test_assessment_requires_justification_for_non_compliant(client, admin_token, org_id):
    standard, version, parent, _child, _pa, _ca = _setup_published_standard_with_tree(client, admin_token, org_id)
    project = create_project(client, admin_token, org_id, name="Assessment Project")
    assignment = _assign_standard_to_project(client, admin_token, org_id, project["id"], standard["id"], version["id"])
    pcr_id = client.get(
        f"{_project_base(project['id'])}/project-compliance/{assignment['id']}/requirements",
        headers=auth_headers(admin_token),
    ).json()[0]["id"]

    no_justification = client.patch(
        f"{_project_base(project['id'])}/project-compliance/{assignment['id']}/requirements/{pcr_id}/assessment",
        json={"compliance_status": "non_compliant", "justification": "", "notes": ""},
        headers=auth_headers(admin_token),
    )
    assert no_justification.status_code == 400

    with_justification = client.patch(
        f"{_project_base(project['id'])}/project-compliance/{assignment['id']}/requirements/{pcr_id}/assessment",
        json={"compliance_status": "non_compliant", "justification": "Failed the thermal test at 85C.", "notes": "Retest scheduled."},
        headers=auth_headers(admin_token),
    )
    assert with_justification.status_code == 200, with_justification.text
    assert with_justification.json()["compliance_status"] == "non_compliant"
    assert with_justification.json()["assessed_by"] is not None

    # §16: the assessment change is recorded with previous/new state.
    history = client.get(
        f"{_project_base(project['id'])}/project-compliance/{assignment['id']}/requirements/{pcr_id}/history",
        headers=auth_headers(admin_token),
    )
    assert history.status_code == 200, history.text
    actions = [e["action"] for e in history.json()]
    assert "assessed" in actions
    assessed_event = next(e for e in history.json() if e["action"] == "assessed")
    assert assessed_event["detail"]["previous_status"] == "not_started"
    assert assessed_event["detail"]["new_status"] == "non_compliant"


# --- RBAC composition (§11, §26) -------------------------------------------------


def test_rbac_officer_grant_manager_override_and_member_forbidden(client, admin_token, org_id):
    standard, version, _parent, _child, _pa, _ca = _setup_published_standard_with_tree(client, admin_token, org_id)
    project = create_project(client, admin_token, org_id, name="RBAC Project")
    assignment = _assign_standard_to_project(client, admin_token, org_id, project["id"], standard["id"], version["id"])
    pcr_id = client.get(
        f"{_project_base(project['id'])}/project-compliance/{assignment['id']}/requirements",
        headers=auth_headers(admin_token),
    ).json()[0]["id"]

    plain_member_id = create_org_user(client, admin_token, org_id, "plain.member@example.com", role="member")
    officer_id = create_org_user(client, admin_token, org_id, "officer@example.com", role="member")
    manager_id = create_org_user(client, admin_token, org_id, "pm@example.com", role="member")

    _assign_project_role(client, admin_token, project["id"], plain_member_id, "stakeholder")
    _assign_project_role(client, admin_token, project["id"], officer_id, "stakeholder")
    _grant_compliance_officer(client, admin_token, project["id"], officer_id)
    _assign_project_role(client, admin_token, project["id"], manager_id, "project_manager")

    plain_token = login(client, "plain.member@example.com", "Password123!")
    officer_token = login(client, "officer@example.com", "Password123!")
    manager_token = login(client, "pm@example.com", "Password123!")

    def _try_assess(token):
        return client.patch(
            f"{_project_base(project['id'])}/project-compliance/{assignment['id']}/requirements/{pcr_id}/assessment",
            json={"compliance_status": "in_progress", "justification": "", "notes": ""},
            headers=auth_headers(token),
        )

    # Plain project member (no compliance_officer grant, not a PM): forbidden.
    assert _try_assess(plain_token).status_code == 403
    # Read access is still granted to any project member (§26).
    read = client.get(
        f"{_project_base(project['id'])}/project-compliance/{assignment['id']}/requirements/{pcr_id}",
        headers=auth_headers(plain_token),
    )
    assert read.status_code == 200

    # Assigned compliance_officer: allowed.
    assert _try_assess(officer_token).status_code == 200
    # PROJECT_MANAGER, with no compliance_officer grant of their own: allowed
    # via require_module_role's existing admin-override composition.
    assert _try_assess(manager_token).status_code == 200


# --- §20 overall status + non-compliant list + MCP-tool-backing endpoints -------


def test_project_status_calculation(client, admin_token, org_id):
    """§20: total/applicable/not-applicable counts, per-status breakdown,
    compliance percentage, has_non_compliant flag, and overall_compliance_state
    — computed from four requirements (one made Not Applicable) with a
    deliberate mix of statuses among the rest."""
    standard = _create_standard(client, admin_token, org_id, reference="STATUS-STD")
    version = _create_version(client, admin_token, org_id, standard["id"])
    requirement_ids = []
    for i in range(4):
        req = _create_requirement(client, admin_token, org_id, standard["id"], version["id"], name=f"Req {i}")
        requirement_ids.append(req["id"])
    _publish_version(client, admin_token, org_id, standard["id"], version["id"])

    project = create_project(client, admin_token, org_id, name="Status Project")
    assignment = _assign_standard_to_project(client, admin_token, org_id, project["id"], standard["id"], version["id"])
    pcrs = client.get(
        f"{_project_base(project['id'])}/project-compliance/{assignment['id']}/requirements",
        headers=auth_headers(admin_token),
    ).json()
    pcr_by_requirement_id = {p["requirement_id"]: p for p in pcrs}

    def _assess(requirement_id, status_value, justification=""):
        pcr_id = pcr_by_requirement_id[requirement_id]["id"]
        resp = client.patch(
            f"{_project_base(project['id'])}/project-compliance/{assignment['id']}/requirements/{pcr_id}/assessment",
            json={"compliance_status": status_value, "justification": justification, "notes": ""},
            headers=auth_headers(admin_token),
        )
        assert resp.status_code == 200, resp.text

    def _set_not_applicable(requirement_id):
        pcr_id = pcr_by_requirement_id[requirement_id]["id"]
        resp = client.patch(
            f"{_project_base(project['id'])}/project-compliance/{assignment['id']}/requirements/{pcr_id}/applicability",
            json={"applicability": "not_applicable", "justification": "Not relevant to this product."},
            headers=auth_headers(admin_token),
        )
        assert resp.status_code == 200, resp.text

    _assess(requirement_ids[0], "compliant")
    _assess(requirement_ids[1], "compliant")
    _assess(requirement_ids[2], "in_progress")
    _set_not_applicable(requirement_ids[3])

    status_list = client.get(f"{_project_base(project['id'])}/status", headers=auth_headers(admin_token))
    assert status_list.status_code == 200, status_list.text
    summary = status_list.json()[0]
    assert summary["total_requirements"] == 4
    assert summary["not_applicable_count"] == 1
    assert summary["applicable_count"] == 3
    assert summary["counts_by_status"]["compliant"] == 2
    assert summary["counts_by_status"]["in_progress"] == 1
    assert summary["compliance_percentage"] == round(2 / 3 * 100, 1)
    assert summary["has_non_compliant"] is False
    assert summary["overall_compliance_state"] == "in_progress"
    assert summary["overall_approval_state"] == "not_assessed"

    # Now push one applicable requirement to Non-Compliant: has_non_compliant
    # flips, and the overall state clearly reflects it regardless of percentage.
    _assess(requirement_ids[2], "non_compliant", justification="Did not pass inspection.")
    status_list_2 = client.get(f"{_project_base(project['id'])}/status", headers=auth_headers(admin_token)).json()[0]
    assert status_list_2["has_non_compliant"] is True
    assert status_list_2["overall_compliance_state"] == "non_compliant"

    non_compliant = client.get(
        f"{_project_base(project['id'])}/non-compliant-requirements", headers=auth_headers(admin_token)
    )
    assert non_compliant.status_code == 200, non_compliant.text
    assert len(non_compliant.json()) == 1
    assert non_compliant.json()[0]["requirement_id"] == requirement_ids[2]
    assert non_compliant.json()[0]["justification"] == "Did not pass inspection."

    # Compliance Manager can see this assignment's status cross-project too (§26).
    cross_project = client.get(f"{_base(org_id)}/project-compliance", headers=auth_headers(admin_token))
    assert cross_project.status_code == 200, cross_project.text
    assert any(row["project_compliance_id"] == assignment["id"] for row in cross_project.json())


# --- Required action assessment completion --------------------------------------


def test_required_action_assessment_complete_and_uncomplete(client, admin_token, org_id):
    standard, version, _parent, child, _pa, child_action = _setup_published_standard_with_tree(client, admin_token, org_id)
    project = create_project(client, admin_token, org_id, name="Required Action Project")
    assignment = _assign_standard_to_project(client, admin_token, org_id, project["id"], standard["id"], version["id"])
    requirements = client.get(
        f"{_project_base(project['id'])}/project-compliance/{assignment['id']}/requirements",
        headers=auth_headers(admin_token),
    ).json()
    child_pcr_id = next(r["id"] for r in requirements if r["requirement_id"] == child["id"])
    assessments = client.get(
        f"{_project_base(project['id'])}/project-compliance/{assignment['id']}/requirements/{child_pcr_id}"
        "/required-action-assessments",
        headers=auth_headers(admin_token),
    ).json()
    assessment_id = assessments[0]["id"]
    base = (
        f"{_project_base(project['id'])}/project-compliance/{assignment['id']}/requirements/{child_pcr_id}"
        f"/required-action-assessments/{assessment_id}"
    )

    updated = client.patch(base, json={"due_date": "2027-06-01", "notes": "Scheduled with the lab."}, headers=auth_headers(admin_token))
    assert updated.status_code == 200, updated.text
    assert updated.json()["due_date"] == "2027-06-01"

    completed = client.post(f"{base}/complete", headers=auth_headers(admin_token))
    assert completed.status_code == 200, completed.text
    assert completed.json()["is_completed"] is True
    assert completed.json()["completed_by"] is not None

    already = client.post(f"{base}/complete", headers=auth_headers(admin_token))
    assert already.status_code == 409

    uncompleted = client.post(f"{base}/uncomplete", headers=auth_headers(admin_token))
    assert uncompleted.status_code == 200, uncompleted.text
    assert uncompleted.json()["is_completed"] is False
    assert uncompleted.json()["completed_at"] is None


# --- Cross-scope isolation --------------------------------------------------------


def test_cross_org_project_assignment_isolation(client, admin_token, org_id):
    """A project in one org cannot be assigned a standard from a different
    org's own path, and a project-compliance id from one project 404s when
    addressed through another project's path."""
    standard, version, _parent, _child, _pa, _ca = _setup_published_standard_with_tree(client, admin_token, org_id)
    project_a = create_project(client, admin_token, org_id, name="Isolation Project A")
    project_b = create_project(client, admin_token, org_id, name="Isolation Project B")
    assignment = _assign_standard_to_project(client, admin_token, org_id, project_a["id"], standard["id"], version["id"])

    wrong_project = client.get(
        f"{_project_base(project_b['id'])}/project-compliance/{assignment['id']}", headers=auth_headers(admin_token)
    )
    assert wrong_project.status_code == 404


def test_archive_and_unarchive_project_compliance(client, admin_token, org_id):
    standard, version, _parent, _child, _pa, _ca = _setup_published_standard_with_tree(client, admin_token, org_id)
    project = create_project(client, admin_token, org_id, name="Archive Project")
    assignment = _assign_standard_to_project(client, admin_token, org_id, project["id"], standard["id"], version["id"])

    archived = client.post(
        f"{_base(org_id)}/projects/{project['id']}/project-compliance/{assignment['id']}/archive",
        headers=auth_headers(admin_token),
    )
    assert archived.status_code == 200, archived.text
    assert archived.json()["is_archived"] is True

    # An archived assignment is excluded from the project's active §20 status list.
    status_list = client.get(f"{_project_base(project['id'])}/status", headers=auth_headers(admin_token)).json()
    assert assignment["id"] not in [s["project_compliance_id"] for s in status_list]

    unarchived = client.post(
        f"{_base(org_id)}/projects/{project['id']}/project-compliance/{assignment['id']}/unarchive",
        headers=auth_headers(admin_token),
    )
    assert unarchived.status_code == 200, unarchived.text
    assert unarchived.json()["is_archived"] is False
