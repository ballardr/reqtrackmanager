"""
Module: test_compliance_review_policy

Compliance's scheduled reviews on the core review engine (`modules.compliance.review_adapter`): the module's own 14-day
lead, the lead a governance review policy sets in its place, the policy's default owner standing in for a review with no
owner while the officers are still told, the due list the engine reads, and a review of a project whose Compliance module
is off being left alone. The notice text, once-per-date stamping and standard-level reviews are pinned by
`test_compliance_reviews_and_notifications.py`.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from app.database import SessionLocal
from app.modules.compliance.tests.test_compliance_evidence_api import _setup_project_with_assessment
from app.modules.compliance.tests.test_project_compliance_api import _assign_project_role, _project_base
from app.services import review_engine
from tests.conftest import auth_headers, create_org_user, login

TODAY = datetime.now(UTC).date()
POLICY = "/api/v1/projects/{project}/modules/traceability/review-policies/compliance_review"


def _review(client, token, project, assignment, days: int, label="Annual", **extra) -> dict:
    resp = client.post(
        f"{_project_base(project['id'])}/project-compliance/{assignment['id']}/reviews",
        json={"frequency_label": label, "next_due_date": (TODAY + timedelta(days=days)).isoformat(), **extra},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _sweep() -> int:
    with SessionLocal() as db:
        return review_engine.send_review_reminders(db)


def _types(client, token) -> list[str]:
    rows = client.get("/api/v1/notifications", headers=auth_headers(token)).json()
    return [r["type"] for r in rows if r["type"].startswith("compliance_review")]


def _governance(client, token, org_id) -> None:
    resp = client.put(
        f"/api/v1/orgs/{org_id}/modules/traceability", json={"enabled": True, "default_project_enabled": True}, headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text


def test_the_modules_own_lead_is_fourteen_days_and_a_policy_lead_replaces_it(client, admin_token, org_id):
    project, assignment, _pcr, _assessment = _setup_project_with_assessment(client, admin_token, org_id)
    _review(client, admin_token, project, assignment, 20)
    assert _sweep() == 0  # 20 days is outside the 14-day lead

    _governance(client, admin_token, org_id)
    set_lead = client.put(POLICY.format(project=project["id"]), json={"settings": {"lead_days": 30}}, headers=auth_headers(admin_token))
    assert set_lead.status_code == 200, set_lead.text
    assert _sweep() == 1
    assert _types(client, admin_token).count("compliance_review_due") >= 1


def test_the_default_owner_stands_in_for_a_review_with_no_owner_and_the_officers_are_still_told(client, admin_token, org_id):
    project, assignment, _pcr, _assessment = _setup_project_with_assessment(client, admin_token, org_id)
    email = f"review.steward.{uuid.uuid4().hex[:8]}@example.com"
    steward_id = create_org_user(client, admin_token, org_id, email, role="member")
    _assign_project_role(client, admin_token, project["id"], steward_id, "stakeholder")
    steward = login(client, email, "Password123!")
    _governance(client, admin_token, org_id)
    named = client.put(
        POLICY.format(project=project["id"]),
        json={"settings": {"default_owner": {"type": "user", "id": steward_id}}}, headers=auth_headers(admin_token),
    )
    assert named.status_code == 200, named.text
    _review(client, admin_token, project, assignment, -2)
    assert _sweep() == 1
    assert _types(client, steward) == ["compliance_review_overdue"]
    assert "compliance_review_overdue" in _types(client, admin_token)


def test_the_engine_reads_the_projects_due_reviews(client, admin_token, org_id):
    project, assignment, _pcr, _assessment = _setup_project_with_assessment(client, admin_token, org_id)
    overdue = _review(client, admin_token, project, assignment, -3, "Overdue one")
    _review(client, admin_token, project, assignment, 40, "Later")
    with SessionLocal() as db:
        due = review_engine.due_reviews(db, uuid.UUID(project["id"]), TODAY)
    assert [(t, str(d.artefact_id)) for t, d in due if t == "compliance_review"] == [("compliance_review", overdue["id"])]


def test_a_project_where_compliance_is_off_is_not_reminded(client, admin_token, org_id):
    project, assignment, _pcr, _assessment = _setup_project_with_assessment(client, admin_token, org_id)
    review = _review(client, admin_token, project, assignment, -1)
    off = client.put(f"/api/v1/projects/{project['id']}/modules/compliance/enablement", json={"enabled": False}, headers=auth_headers(admin_token))
    assert off.status_code == 200, off.text
    _sweep()
    rows = client.get("/api/v1/notifications", headers=auth_headers(admin_token)).json()
    assert review["id"] not in {r["entity_id"] for r in rows}
