"""Tests for the Compliance Module's Phase 10 Scheduled Reviews +
Notifications (docs/compliance-module-plan.md Phase 10; docs/Compliance_
Module_Requirements.md §17, §18, §28): the `ComplianceReview` CRUD/complete/
evidence-linkage surface on both the org router (standard-level reviews)
and the project router (project-level reviews), the computed `schedule_
state` derivation, the unified `reviews-due` listing, the four date-driven
notification sweeps (`app.modules.compliance.scheduler`), and the six
event-driven notifications wired into the Phase 6/7/9 endpoints this phase
extends.

Reuses `test_compliance_standards_api.py`'s and `test_project_compliance_
api.py`'s helpers for setup, the same way `test_compliance_evidence_api.py`/
`test_compliance_approval_workflow.py` already do.
"""

from __future__ import annotations

from datetime import date, timedelta

from app.database import SessionLocal
from app.modules.compliance.scheduler import (
    send_evidence_expiry_notifications,
    send_required_action_due_notifications,
    send_review_due_notifications,
    send_target_date_notifications,
)
from app.modules.compliance.tests.test_compliance_evidence_api import _create_evidence, _setup_project_with_assessment
from app.modules.compliance.tests.test_compliance_standards_api import _base
from app.modules.compliance.tests.test_project_compliance_api import (
    _assign_project_role,
    _assign_standard_to_project,
    _grant_compliance_officer,
    _project_base,
    _setup_published_standard_with_tree,
)
from tests.conftest import auth_headers, create_org_user, create_project, login

TODAY = date.today()


def _notifications_for(client, token):
    return client.get("/api/v1/notifications", headers=auth_headers(token)).json()


def _run_sweep(fn) -> None:
    db = SessionLocal()
    try:
        fn(db)
    finally:
        db.close()


# --- Project-level review CRUD (project router) -----------------------------------


def test_create_list_get_project_review(client, admin_token, org_id):
    project, assignment, _pcr_id, _assessment_id = _setup_project_with_assessment(client, admin_token, org_id)

    created = client.post(
        f"{_project_base(project['id'])}/project-compliance/{assignment['id']}/reviews",
        json={"frequency_label": "Annual", "recurrence_days": 365, "next_due_date": (TODAY + timedelta(days=200)).isoformat()},
        headers=auth_headers(admin_token),
    )
    assert created.status_code == 201, created.text
    review = created.json()
    assert review["status"] == "scheduled"
    assert review["schedule_state"] == "upcoming"
    assert review["outcome"] is None
    assert review["linked_evidence_ids"] == []

    listed = client.get(
        f"{_project_base(project['id'])}/project-compliance/{assignment['id']}/reviews", headers=auth_headers(admin_token)
    )
    assert listed.status_code == 200
    assert [r["id"] for r in listed.json()] == [review["id"]]

    fetched = client.get(f"{_project_base(project['id'])}/reviews/{review['id']}", headers=auth_headers(admin_token))
    assert fetched.status_code == 200
    assert fetched.json()["id"] == review["id"]


def test_schedule_state_reflects_next_due_date(client, admin_token, org_id):
    project, assignment, _pcr_id, _assessment_id = _setup_project_with_assessment(client, admin_token, org_id)

    def _create(next_due_date):
        resp = client.post(
            f"{_project_base(project['id'])}/project-compliance/{assignment['id']}/reviews",
            json={"frequency_label": "Ad hoc", "next_due_date": next_due_date.isoformat()},
            headers=auth_headers(admin_token),
        )
        assert resp.status_code == 201, resp.text
        return resp.json()

    upcoming = _create(TODAY + timedelta(days=60))
    due = _create(TODAY + timedelta(days=5))
    overdue = _create(TODAY - timedelta(days=5))

    assert upcoming["schedule_state"] == "upcoming"
    assert due["schedule_state"] == "due"
    assert overdue["schedule_state"] == "overdue"


def test_update_only_while_scheduled_and_resets_reminder_stamps(client, admin_token, org_id):
    project, assignment, _pcr_id, _assessment_id = _setup_project_with_assessment(client, admin_token, org_id)
    review = client.post(
        f"{_project_base(project['id'])}/project-compliance/{assignment['id']}/reviews",
        json={"frequency_label": "Annual", "next_due_date": (TODAY - timedelta(days=1)).isoformat()},
        headers=auth_headers(admin_token),
    ).json()

    # Push the sweep's overdue stamp onto this review, then confirm PATCHing
    # a new next_due_date clears it (a rescheduled review gets a fresh
    # reminder cycle rather than silently inheriting the old "already
    # notified" state).
    _run_sweep(send_review_due_notifications)

    updated = client.patch(
        f"{_project_base(project['id'])}/reviews/{review['id']}",
        json={"frequency_label": "Annual", "next_due_date": (TODAY + timedelta(days=90)).isoformat()},
        headers=auth_headers(admin_token),
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["schedule_state"] == "upcoming"

    complete = client.post(
        f"{_project_base(project['id'])}/reviews/{review['id']}/complete",
        json={"outcome": "satisfactory"}, headers=auth_headers(admin_token),
    )
    assert complete.status_code == 200, complete.text

    cannot_edit = client.patch(
        f"{_project_base(project['id'])}/reviews/{review['id']}",
        json={"frequency_label": "Annual", "next_due_date": (TODAY + timedelta(days=1)).isoformat()},
        headers=auth_headers(admin_token),
    )
    assert cannot_edit.status_code == 409


def test_complete_review_with_recurrence_schedules_next_cycle(client, admin_token, org_id):
    project, assignment, _pcr_id, _assessment_id = _setup_project_with_assessment(client, admin_token, org_id)
    review = client.post(
        f"{_project_base(project['id'])}/project-compliance/{assignment['id']}/reviews",
        json={"frequency_label": "Annual", "recurrence_days": 365, "next_due_date": TODAY.isoformat()},
        headers=auth_headers(admin_token),
    ).json()

    completed = client.post(
        f"{_project_base(project['id'])}/reviews/{review['id']}/complete",
        json={"outcome": "action_required", "notes": "Found two gaps."}, headers=auth_headers(admin_token),
    )
    assert completed.status_code == 200, completed.text
    body = completed.json()
    assert body["status"] == "completed"
    assert body["outcome"] == "action_required"
    assert body["notes"] == "Found two gaps."
    assert body["schedule_state"] is None
    assert body["completed_at"] is not None
    assert body["completed_by"] is not None

    history = client.get(
        f"{_project_base(project['id'])}/project-compliance/{assignment['id']}/reviews", headers=auth_headers(admin_token)
    ).json()
    assert len(history) == 2
    completed_row = next(r for r in history if r["id"] == review["id"])
    next_row = next(r for r in history if r["id"] != review["id"])
    assert completed_row["status"] == "completed"
    assert next_row["status"] == "scheduled"
    assert next_row["next_due_date"] == (TODAY + timedelta(days=365)).isoformat()

    # 409 on a second completion attempt of the already-completed row.
    again = client.post(
        f"{_project_base(project['id'])}/reviews/{review['id']}/complete",
        json={"outcome": "satisfactory"}, headers=auth_headers(admin_token),
    )
    assert again.status_code == 409


def test_complete_review_without_recurrence_does_not_recur(client, admin_token, org_id):
    project, assignment, _pcr_id, _assessment_id = _setup_project_with_assessment(client, admin_token, org_id)
    review = client.post(
        f"{_project_base(project['id'])}/project-compliance/{assignment['id']}/reviews",
        json={"frequency_label": "Before product release", "next_due_date": TODAY.isoformat()},
        headers=auth_headers(admin_token),
    ).json()

    client.post(
        f"{_project_base(project['id'])}/reviews/{review['id']}/complete",
        json={"outcome": "satisfactory"}, headers=auth_headers(admin_token),
    )
    history = client.get(
        f"{_project_base(project['id'])}/project-compliance/{assignment['id']}/reviews", headers=auth_headers(admin_token)
    ).json()
    assert len(history) == 1


def test_delete_review_only_while_scheduled(client, admin_token, org_id):
    project, assignment, _pcr_id, _assessment_id = _setup_project_with_assessment(client, admin_token, org_id)
    review = client.post(
        f"{_project_base(project['id'])}/project-compliance/{assignment['id']}/reviews",
        json={"frequency_label": "Annual", "next_due_date": TODAY.isoformat()},
        headers=auth_headers(admin_token),
    ).json()
    client.post(
        f"{_project_base(project['id'])}/reviews/{review['id']}/complete",
        json={"outcome": "satisfactory"}, headers=auth_headers(admin_token),
    )
    cannot_delete = client.delete(f"{_project_base(project['id'])}/reviews/{review['id']}", headers=auth_headers(admin_token))
    assert cannot_delete.status_code == 409

    other = client.post(
        f"{_project_base(project['id'])}/project-compliance/{assignment['id']}/reviews",
        json={"frequency_label": "Annual", "next_due_date": TODAY.isoformat()},
        headers=auth_headers(admin_token),
    ).json()
    deleted = client.delete(f"{_project_base(project['id'])}/reviews/{other['id']}", headers=auth_headers(admin_token))
    assert deleted.status_code == 204


def test_review_evidence_linkage(client, admin_token, org_id):
    project, assignment, pcr_id, _assessment_id = _setup_project_with_assessment(client, admin_token, org_id)
    review = client.post(
        f"{_project_base(project['id'])}/project-compliance/{assignment['id']}/reviews",
        json={"frequency_label": "Annual", "next_due_date": TODAY.isoformat()},
        headers=auth_headers(admin_token),
    ).json()
    evidence = _create_evidence(
        client, admin_token, project["id"], project_compliance_requirement_ids=[pcr_id],
    )

    linked = client.post(
        f"{_project_base(project['id'])}/reviews/{review['id']}/evidence-links",
        json={"evidence_id": evidence["id"]}, headers=auth_headers(admin_token),
    )
    assert linked.status_code == 201, linked.text
    assert linked.json()["linked_evidence_ids"] == [evidence["id"]]

    unlinked = client.delete(
        f"{_project_base(project['id'])}/reviews/{review['id']}/evidence-links/{evidence['id']}",
        headers=auth_headers(admin_token),
    )
    assert unlinked.status_code == 204
    refetched = client.get(f"{_project_base(project['id'])}/reviews/{review['id']}", headers=auth_headers(admin_token))
    assert refetched.json()["linked_evidence_ids"] == []


def test_project_review_rbac_composition(client, admin_token, org_id):
    project, assignment, _pcr_id, _assessment_id = _setup_project_with_assessment(client, admin_token, org_id, project_name="RBAC Project")
    member_id = create_org_user(client, admin_token, org_id, "review-member@example.com", role="member")
    _assign_project_role(client, admin_token, project["id"], member_id, "stakeholder")
    member_token = login(client, "review-member@example.com", "Password123!")

    forbidden = client.post(
        f"{_project_base(project['id'])}/project-compliance/{assignment['id']}/reviews",
        json={"frequency_label": "Annual", "next_due_date": TODAY.isoformat()},
        headers=auth_headers(member_token),
    )
    assert forbidden.status_code == 403

    officer_id = create_org_user(client, admin_token, org_id, "review-officer@example.com", role="member")
    _grant_compliance_officer(client, admin_token, project["id"], officer_id)
    officer_token = login(client, "review-officer@example.com", "Password123!")
    allowed = client.post(
        f"{_project_base(project['id'])}/project-compliance/{assignment['id']}/reviews",
        json={"frequency_label": "Annual", "next_due_date": TODAY.isoformat()},
        headers=auth_headers(officer_token),
    )
    assert allowed.status_code == 201, allowed.text

    # Any project member may read.
    readable = client.get(
        f"{_project_base(project['id'])}/project-compliance/{assignment['id']}/reviews", headers=auth_headers(member_token)
    )
    assert readable.status_code == 200


# --- Standard-level review CRUD (org router) --------------------------------------


def test_standard_review_rbac_and_lifecycle(client, admin_token, org_id):
    tree = _setup_published_standard_with_tree(client, admin_token, org_id)
    standard, _version, _parent, _child, _pa, _ca = tree

    create_org_user(client, admin_token, org_id, "standard-review-member@example.com", role="member")
    member_token = login(client, "standard-review-member@example.com", "Password123!")
    forbidden = client.post(
        f"{_base(org_id)}/standards/{standard['id']}/reviews",
        json={"frequency_label": "Annual", "next_due_date": TODAY.isoformat()},
        headers=auth_headers(member_token),
    )
    assert forbidden.status_code == 403

    created = client.post(
        f"{_base(org_id)}/standards/{standard['id']}/reviews",
        json={"frequency_label": "Annual", "recurrence_days": 365, "next_due_date": TODAY.isoformat()},
        headers=auth_headers(admin_token),
    )
    assert created.status_code == 201, created.text
    review = created.json()
    assert review["standard_id"] == standard["id"]
    assert review["project_compliance_id"] is None

    completed = client.post(
        f"{_base(org_id)}/standards/{standard['id']}/reviews/{review['id']}/complete",
        json={"outcome": "satisfactory"}, headers=auth_headers(admin_token),
    )
    assert completed.status_code == 200
    history = client.get(f"{_base(org_id)}/standards/{standard['id']}/reviews", headers=auth_headers(admin_token)).json()
    assert len(history) == 2


# --- Unified reviews-due listing ---------------------------------------------------


def test_reviews_due_listing_spans_project_and_standard_level(client, admin_token, org_id):
    tree = _setup_published_standard_with_tree(client, admin_token, org_id)
    standard, version, _parent, _child, _pa, _ca = tree
    project = create_project(client, admin_token, org_id, name="Reviews Due Project")
    assignment = _assign_standard_to_project(client, admin_token, org_id, project["id"], standard["id"], version["id"])

    due_project_review = client.post(
        f"{_project_base(project['id'])}/project-compliance/{assignment['id']}/reviews",
        json={"frequency_label": "Annual", "next_due_date": (TODAY + timedelta(days=1)).isoformat()},
        headers=auth_headers(admin_token),
    ).json()
    client.post(
        f"{_project_base(project['id'])}/project-compliance/{assignment['id']}/reviews",
        json={"frequency_label": "Not due yet", "next_due_date": (TODAY + timedelta(days=200)).isoformat()},
        headers=auth_headers(admin_token),
    )
    due_standard_review = client.post(
        f"{_base(org_id)}/standards/{standard['id']}/reviews",
        json={"frequency_label": "Standard audit", "next_due_date": (TODAY - timedelta(days=1)).isoformat()},
        headers=auth_headers(admin_token),
    ).json()

    due_listing = client.get(f"{_project_base(project['id'])}/reviews-due", headers=auth_headers(admin_token))
    assert due_listing.status_code == 200
    ids = {r["id"] for r in due_listing.json()}
    assert ids == {due_project_review["id"], due_standard_review["id"]}


# --- Event-driven notifications -----------------------------------------------------


def _second_officer(client, admin_token, org_id, project_id, email="second-officer@example.com"):
    user_id = create_org_user(client, admin_token, org_id, email, role="member")
    _grant_compliance_officer(client, admin_token, project_id, user_id)
    return login(client, email, "Password123!")


def test_non_compliant_assessment_notifies_compliance_officers(client, admin_token, org_id):
    project, assignment, pcr_id, _assessment_id = _setup_project_with_assessment(client, admin_token, org_id)
    officer_token = _second_officer(client, admin_token, org_id, project["id"])

    resp = client.patch(
        f"{_project_base(project['id'])}/project-compliance/{assignment['id']}/requirements/{pcr_id}/assessment",
        json={"compliance_status": "non_compliant", "justification": "Failed thermal test."},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 200, resp.text

    notifs = _notifications_for(client, officer_token)
    assert any(n["type"] == "compliance_requirement_non_compliant" for n in notifs)


def test_submit_for_approval_notifies_compliance_officers(client, admin_token, org_id):
    project, assignment, pcr_id, _assessment_id = _setup_project_with_assessment(client, admin_token, org_id)
    officer_token = _second_officer(client, admin_token, org_id, project["id"])
    client.patch(
        f"{_project_base(project['id'])}/project-compliance/{assignment['id']}/requirements/{pcr_id}/assessment",
        json={"compliance_status": "compliant", "justification": ""}, headers=auth_headers(admin_token),
    )
    client.post(
        f"{_project_base(project['id'])}/project-compliance/{assignment['id']}/requirements/{pcr_id}/submit-for-approval",
        headers=auth_headers(admin_token),
    )
    notifs = _notifications_for(client, officer_token)
    assert any(n["type"] == "compliance_approval_requested" for n in notifs)


def test_reject_notifies_the_assessor(client, admin_token, org_id):
    project, assignment, pcr_id, _assessment_id = _setup_project_with_assessment(client, admin_token, org_id)
    assessor_id = create_org_user(client, admin_token, org_id, "assessor@example.com", role="member")
    _grant_compliance_officer(client, admin_token, project["id"], assessor_id)
    assessor_token = login(client, "assessor@example.com", "Password123!")

    client.patch(
        f"{_project_base(project['id'])}/project-compliance/{assignment['id']}/requirements/{pcr_id}/assessment",
        json={"compliance_status": "compliant", "justification": ""}, headers=auth_headers(assessor_token),
    )
    client.post(
        f"{_project_base(project['id'])}/project-compliance/{assignment['id']}/requirements/{pcr_id}/submit-for-approval",
        headers=auth_headers(assessor_token),
    )
    rejected = client.post(
        f"{_project_base(project['id'])}/project-compliance/{assignment['id']}/requirements/{pcr_id}/reject",
        json={"decision_note": "Not sufficient."}, headers=auth_headers(admin_token),
    )
    assert rejected.status_code == 200, rejected.text

    notifs = _notifications_for(client, assessor_token)
    assert any(n["type"] == "compliance_assessment_rejected" for n in notifs)


def test_applicability_change_invalidating_approval_notifies_officers(client, admin_token, org_id):
    project, assignment, pcr_id, _assessment_id = _setup_project_with_assessment(client, admin_token, org_id)
    officer_token = _second_officer(client, admin_token, org_id, project["id"])

    client.patch(
        f"{_project_base(project['id'])}/project-compliance/{assignment['id']}/requirements/{pcr_id}/assessment",
        json={"compliance_status": "compliant", "justification": ""}, headers=auth_headers(admin_token),
    )
    client.post(
        f"{_project_base(project['id'])}/project-compliance/{assignment['id']}/requirements/{pcr_id}/submit-for-approval",
        headers=auth_headers(admin_token),
    )
    client.post(
        f"{_project_base(project['id'])}/project-compliance/{assignment['id']}/requirements/{pcr_id}/approve",
        json={}, headers=auth_headers(admin_token),
    )
    changed = client.patch(
        f"{_project_base(project['id'])}/project-compliance/{assignment['id']}/requirements/{pcr_id}/applicability",
        json={"applicability": "not_applicable", "justification": "Scope changed."}, headers=auth_headers(admin_token),
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["approval_state"] == "requires_reassessment"

    notifs = _notifications_for(client, officer_token)
    assert any(n["type"] == "compliance_approval_invalidated" for n in notifs)


def test_publish_new_version_notifies_officers_of_projects_on_older_version(client, admin_token, org_id):
    tree = _setup_published_standard_with_tree(client, admin_token, org_id)
    standard, version, _parent, _child, _pa, _ca = tree
    project = create_project(client, admin_token, org_id, name="Pinned Project")
    _assign_standard_to_project(client, admin_token, org_id, project["id"], standard["id"], version["id"])
    officer_token = _second_officer(client, admin_token, org_id, project["id"], email="pinned-officer@example.com")

    new_version = client.post(
        f"{_base(org_id)}/standards/{standard['id']}/versions",
        json={"version_label": "2.1", "clone_from_version_id": version["id"]}, headers=auth_headers(admin_token),
    )
    assert new_version.status_code == 201, new_version.text
    published = client.post(
        f"{_base(org_id)}/standards/{standard['id']}/versions/{new_version.json()['id']}/publish",
        headers=auth_headers(admin_token),
    )
    assert published.status_code == 200, published.text

    notifs = _notifications_for(client, officer_token)
    assert any(n["type"] == "compliance_standard_update_review_needed" for n in notifs)


def test_new_assignment_notifies_compliance_officers(client, admin_token, org_id):
    tree = _setup_published_standard_with_tree(client, admin_token, org_id)
    standard, version, _parent, _child, _pa, _ca = tree
    project = create_project(client, admin_token, org_id, name="New Assignment Project")
    officer_id = create_org_user(client, admin_token, org_id, "assignment-officer@example.com", role="member")
    _grant_compliance_officer(client, admin_token, project["id"], officer_id)
    officer_token = login(client, "assignment-officer@example.com", "Password123!")

    _assign_standard_to_project(client, admin_token, org_id, project["id"], standard["id"], version["id"])

    notifs = _notifications_for(client, officer_token)
    assert any(n["type"] == "compliance_assignment_created" for n in notifs)


# --- Date-driven sweeps -------------------------------------------------------------


def test_evidence_expiry_sweep_notifies_once_per_state(client, admin_token, org_id):
    project, _assignment, pcr_id, _assessment_id = _setup_project_with_assessment(client, admin_token, org_id)
    officer_token = _second_officer(client, admin_token, org_id, project["id"], email="evidence-officer@example.com")
    _create_evidence(
        client, admin_token, project["id"], expiry_date=(TODAY - timedelta(days=1)).isoformat(),
        project_compliance_requirement_ids=[pcr_id],
    )

    _run_sweep(send_evidence_expiry_notifications)
    _run_sweep(send_evidence_expiry_notifications)

    notifs = [n for n in _notifications_for(client, officer_token) if n["type"] == "compliance_evidence_expired"]
    assert len(notifs) == 1


def test_required_action_due_sweep_notifies_assignee(client, admin_token, org_id):
    project, assignment, pcr_id, assessment_id = _setup_project_with_assessment(client, admin_token, org_id)
    assignee_id = create_org_user(client, admin_token, org_id, "action-assignee@example.com", role="member")
    _assign_project_role(client, admin_token, project["id"], assignee_id, "stakeholder")
    assignee_token = login(client, "action-assignee@example.com", "Password123!")

    updated = client.patch(
        f"{_project_base(project['id'])}/project-compliance/{assignment['id']}/requirements/{pcr_id}/"
        f"required-action-assessments/{assessment_id}",
        json={"assignee_id": assignee_id, "due_date": (TODAY - timedelta(days=1)).isoformat()},
        headers=auth_headers(admin_token),
    )
    assert updated.status_code == 200, updated.text

    _run_sweep(send_required_action_due_notifications)
    _run_sweep(send_required_action_due_notifications)

    notifs = [
        n for n in _notifications_for(client, assignee_token) if n["type"] == "compliance_required_action_overdue"
    ]
    assert len(notifs) == 1


def test_target_date_sweep_notifies_officers(client, admin_token, org_id):
    tree = _setup_published_standard_with_tree(client, admin_token, org_id)
    standard, version, _parent, _child, _pa, _ca = tree
    project = create_project(client, admin_token, org_id, name="Target Date Project")
    officer_token = _second_officer(client, admin_token, org_id, project["id"], email="target-officer@example.com")
    _assign_standard_to_project(
        client, admin_token, org_id, project["id"], standard["id"], version["id"],
        target_compliance_date=(TODAY - timedelta(days=1)).isoformat(),
    )

    _run_sweep(send_target_date_notifications)
    _run_sweep(send_target_date_notifications)

    notifs = [
        n for n in _notifications_for(client, officer_token) if n["type"] == "compliance_target_date_exceeded"
    ]
    assert len(notifs) == 1


def test_review_due_sweep_notifies_owner(client, admin_token, org_id):
    project, assignment, _pcr_id, _assessment_id = _setup_project_with_assessment(client, admin_token, org_id)
    owner_id = create_org_user(client, admin_token, org_id, "review-owner@example.com", role="member")
    owner_token = login(client, "review-owner@example.com", "Password123!")

    client.post(
        f"{_project_base(project['id'])}/project-compliance/{assignment['id']}/reviews",
        json={"frequency_label": "Annual", "next_due_date": (TODAY - timedelta(days=1)).isoformat(), "owner_id": owner_id},
        headers=auth_headers(admin_token),
    )

    _run_sweep(send_review_due_notifications)
    _run_sweep(send_review_due_notifications)

    notifs = [n for n in _notifications_for(client, owner_token) if n["type"] == "compliance_review_overdue"]
    assert len(notifs) == 1
