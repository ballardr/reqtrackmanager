"""The reminder before a stage's review deadline (`services.stages.STAGE_REVIEW_ADAPTER` on the review engine): who is
reminded (stakeholders who have not responded, and the project managers), once per deadline and again when the deadline
changes, the cases that are not reminded (no deadline, outside the lead window, not in review, an archived project) and
that a deadline that has passed is approved automatically as before."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.database import SessionLocal
from app.services import review_engine
from app.services.stages import auto_approve_overdue_stage_reviews
from tests.conftest import auth_headers, create_org_user, create_project, login
from tests.stage_helpers import move_stage

KIND = "stage_review_deadline"


def _url(project_id, tail="") -> str:
    return f"/api/v1/projects/{project_id}/{tail}"


def _stage_id(client, token, project_id) -> str:
    return client.get(_url(project_id, "stages"), headers=auth_headers(token)).json()[0]["id"]


def _stakeholder(client, admin_token, org_id, project_id, email) -> str:
    user_id = create_org_user(client, admin_token, org_id, email)
    resp = client.post(_url(project_id, "roles"), json={"user_id": user_id, "role": "stakeholder"}, headers=auth_headers(admin_token))
    assert resp.status_code in (200, 201, 204), resp.text
    return login(client, email, "Password123!")


def _deadline(client, token, project_id, stage_id, at: datetime) -> None:
    resp = client.post(
        _url(project_id, f"stages/{stage_id}/review-deadline"), json={"review_deadline": at.isoformat()}, headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text


def _in_review(client, token, project_id, days_ahead: float | None = 3) -> str:
    stage_id = _stage_id(client, token, project_id)
    moved = move_stage(client, project_id, stage_id, "review", headers=auth_headers(token))
    assert moved.status_code == 200, moved.text
    if days_ahead is not None:
        _deadline(client, token, project_id, stage_id, datetime.now(UTC) + timedelta(days=days_ahead))
    return stage_id


def _sweep() -> int:
    with SessionLocal() as db:
        return review_engine.send_review_reminders(db)


def _inbox(client, token) -> list[dict]:
    return [n for n in client.get("/api/v1/notifications", headers=auth_headers(token)).json() if n["type"] == KIND]


def test_the_managers_and_the_stakeholders_who_have_not_responded_are_reminded_once(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    pid = project["id"]
    waiting = _stakeholder(client, admin_token, org_id, pid, "waiting@example.com")
    answered = _stakeholder(client, admin_token, org_id, pid, "answered@example.com")
    stage_id = _in_review(client, admin_token, pid)
    resp = client.post(
        _url(pid, f"stages/{stage_id}/review-response"), json={"response": "approved"}, headers=auth_headers(answered),
    )
    assert resp.status_code in (200, 201), resp.text

    assert _sweep() == 1
    assert _sweep() == 0
    assert len(_inbox(client, waiting)) == 1
    assert len(_inbox(client, admin_token)) == 1
    assert _inbox(client, answered) == []
    assert "approved automatically" in _inbox(client, waiting)[0]["body"]


def test_a_stakeholder_who_rejected_is_not_reminded_but_the_managers_are(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    pid = project["id"]
    objector = _stakeholder(client, admin_token, org_id, pid, "objector@example.com")
    stage_id = _in_review(client, admin_token, pid)
    resp = client.post(
        _url(pid, f"stages/{stage_id}/review-response"), json={"response": "rejected", "comment": "No."}, headers=auth_headers(objector),
    )
    assert resp.status_code in (200, 201), resp.text
    assert _sweep() == 1
    assert _inbox(client, objector) == []
    assert len(_inbox(client, admin_token)) == 1


def test_a_changed_deadline_is_reminded_again(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    pid = project["id"]
    waiting = _stakeholder(client, admin_token, org_id, pid, "again@example.com")
    stage_id = _in_review(client, admin_token, pid, 3)
    assert _sweep() == 1
    _deadline(client, admin_token, pid, stage_id, datetime.now(UTC) + timedelta(days=4))
    assert _sweep() == 1
    assert len(_inbox(client, waiting)) == 2


def test_no_reminder_without_a_deadline_outside_the_lead_or_when_the_stage_is_not_in_review(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    pid = project["id"]
    stage_id = _in_review(client, admin_token, pid, None)
    assert _sweep() == 0  # no deadline
    _deadline(client, admin_token, pid, stage_id, datetime.now(UTC) + timedelta(days=10))
    assert _sweep() == 0  # beyond the seven-day lead
    _deadline(client, admin_token, pid, stage_id, datetime.now(UTC) + timedelta(days=3))
    assert move_stage(client, pid, stage_id, "scoping", headers=auth_headers(admin_token)).status_code == 200
    assert _sweep() == 0  # no longer in a review phase
    assert _inbox(client, admin_token) == []


def test_an_archived_project_is_not_reminded(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    _in_review(client, admin_token, project["id"])
    assert client.post(_url(project["id"], "archive"), headers=auth_headers(admin_token)).status_code == 200
    assert _sweep() == 0


def test_a_deadline_that_has_passed_is_approved_not_reminded(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    pid = project["id"]
    stage_id = _in_review(client, admin_token, pid, -1)
    assert _sweep() == 0
    with SessionLocal() as db:
        auto_approve_overdue_stage_reviews(db)
    stage = next(s for s in client.get(_url(pid, "stages"), headers=auth_headers(admin_token)).json() if s["id"] == stage_id)
    assert stage["phase_kind"] == "locked"
