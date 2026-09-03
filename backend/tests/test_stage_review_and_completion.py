"""Tests for Massif (v3) stage review-deadline auto-approval (C-R-05) and
completion tracking (C-P-02, C-P-03)."""

from datetime import UTC, datetime, timedelta

from app.database import SessionLocal
from app.services.stages import auto_approve_overdue_stage_reviews
from tests.conftest import auth_headers, create_component_and_category, create_org_user, create_project, login


def _current_stage_id(client, token, project_id) -> str:
    stages = client.get(f"/api/v1/projects/{project_id}/stages", headers=auth_headers(token)).json()
    return stages[0]["id"]


def test_stage_review_deadline_requires_stage_to_be_in_review(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    stage_id = _current_stage_id(client, admin_token, project["id"])
    resp = client.post(
        f"/api/v1/projects/{project['id']}/stages/{stage_id}/review-deadline",
        json={"review_deadline": datetime.now(UTC).isoformat()}, headers=auth_headers(admin_token),
    )
    assert resp.status_code == 409


def test_overdue_stage_review_auto_approves_when_no_rejection(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    stage_id = _current_stage_id(client, admin_token, project["id"])
    client.post(
        f"/api/v1/projects/{project['id']}/stages/{stage_id}/transition",
        params={"new_status": "review"}, headers=auth_headers(admin_token),
    )
    client.post(
        f"/api/v1/projects/{project['id']}/stages/{stage_id}/review-deadline",
        json={"review_deadline": (datetime.now(UTC) - timedelta(days=1)).isoformat()}, headers=auth_headers(admin_token),
    )

    db = SessionLocal()
    try:
        auto_approve_overdue_stage_reviews(db)
    finally:
        db.close()

    resp = client.get(f"/api/v1/projects/{project['id']}/stages", headers=auth_headers(admin_token))
    stage = next(s for s in resp.json() if s["id"] == stage_id)
    assert stage["status"] == "approved"
    assert stage["approved_at"] is not None


def test_overdue_stage_review_does_not_auto_approve_after_explicit_rejection(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    stage_id = _current_stage_id(client, admin_token, project["id"])
    client.post(
        f"/api/v1/projects/{project['id']}/stages/{stage_id}/transition",
        params={"new_status": "review"}, headers=auth_headers(admin_token),
    )
    client.post(
        f"/api/v1/projects/{project['id']}/stages/{stage_id}/review-deadline",
        json={"review_deadline": (datetime.now(UTC) - timedelta(days=1)).isoformat()}, headers=auth_headers(admin_token),
    )
    resp = client.post(
        f"/api/v1/projects/{project['id']}/stages/{stage_id}/review-response",
        json={"response": "rejected", "comment": "Not ready."}, headers=auth_headers(admin_token),
    )
    assert resp.status_code == 200

    db = SessionLocal()
    try:
        auto_approve_overdue_stage_reviews(db)
    finally:
        db.close()

    resp = client.get(f"/api/v1/projects/{project['id']}/stages", headers=auth_headers(admin_token))
    stage = next(s for s in resp.json() if s["id"] == stage_id)
    assert stage["status"] == "review"


def test_mark_requirement_completed_requires_approved_status(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    req = client.post(
        f"/api/v1/projects/{project['id']}/requirements",
        json={"name": "Req", "component_id": component_id, "category_id": category_id},
        headers=auth_headers(admin_token),
    ).json()

    resp = client.post(f"/api/v1/projects/{project['id']}/requirements/{req['id']}/complete", headers=auth_headers(admin_token))
    assert resp.status_code == 409

    client.put(
        f"/api/v1/projects/{project['id']}/requirements/{req['id']}",
        json={
            "name": req["name"], "component_id": component_id, "category_id": category_id,
            "owner_id": req["owner_id"], "status": "approved",
        },
        headers=auth_headers(admin_token),
    )
    resp = client.post(f"/api/v1/projects/{project['id']}/requirements/{req['id']}/complete", headers=auth_headers(admin_token))
    assert resp.status_code == 200
    # C-G-11: completing is an overlay marker, not a status transition —
    # `status` stays "approved" throughout; `is_completed` is what flips.
    assert resp.json()["status"] == "approved"
    assert resp.json()["is_completed"] is True
    assert resp.json()["completed_at"] is not None
    assert resp.json()["completed_by"] is not None


def test_complete_and_uncomplete_do_not_bump_the_version_number(client, admin_token, org_id):
    """Marking completed/uncompleted doesn't change a requirement's content,
    so unlike every other status/content edit it must not create a new
    `RequirementVersion` — pins that against a regression back to the old
    `apply_new_version`-based implementation."""
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    req = client.post(
        f"/api/v1/projects/{project['id']}/requirements",
        json={"name": "Req", "component_id": component_id, "category_id": category_id},
        headers=auth_headers(admin_token),
    ).json()
    client.post(
        f"/api/v1/projects/{project['id']}/requirements/{req['id']}/approve", headers=auth_headers(admin_token)
    )
    history_before = client.get(
        f"/api/v1/projects/{project['id']}/requirements/{req['id']}/history", headers=auth_headers(admin_token)
    ).json()

    complete_resp = client.post(f"/api/v1/projects/{project['id']}/requirements/{req['id']}/complete", headers=auth_headers(admin_token))
    assert complete_resp.status_code == 200, complete_resp.text
    history_after_complete = client.get(
        f"/api/v1/projects/{project['id']}/requirements/{req['id']}/history", headers=auth_headers(admin_token)
    ).json()
    assert len(history_after_complete) == len(history_before)

    uncomplete_resp = client.post(f"/api/v1/projects/{project['id']}/requirements/{req['id']}/uncomplete", headers=auth_headers(admin_token))
    assert uncomplete_resp.status_code == 200, uncomplete_resp.text
    assert uncomplete_resp.json()["is_completed"] is False
    assert uncomplete_resp.json()["status"] == "approved"
    history_after_uncomplete = client.get(
        f"/api/v1/projects/{project['id']}/requirements/{req['id']}/history", headers=auth_headers(admin_token)
    ).json()
    assert len(history_after_uncomplete) == len(history_before)


def test_double_complete_is_rejected(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    req = client.post(
        f"/api/v1/projects/{project['id']}/requirements",
        json={"name": "Req", "component_id": component_id, "category_id": category_id},
        headers=auth_headers(admin_token),
    ).json()
    client.post(f"/api/v1/projects/{project['id']}/requirements/{req['id']}/approve", headers=auth_headers(admin_token))
    first = client.post(f"/api/v1/projects/{project['id']}/requirements/{req['id']}/complete", headers=auth_headers(admin_token))
    assert first.status_code == 200

    second = client.post(f"/api/v1/projects/{project['id']}/requirements/{req['id']}/complete", headers=auth_headers(admin_token))
    assert second.status_code == 409


def test_uncomplete_rejects_a_requirement_that_is_not_completed(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    req = client.post(
        f"/api/v1/projects/{project['id']}/requirements",
        json={"name": "Req", "component_id": component_id, "category_id": category_id},
        headers=auth_headers(admin_token),
    ).json()
    client.post(f"/api/v1/projects/{project['id']}/requirements/{req['id']}/approve", headers=auth_headers(admin_token))

    resp = client.post(f"/api/v1/projects/{project['id']}/requirements/{req['id']}/uncomplete", headers=auth_headers(admin_token))
    assert resp.status_code == 409


def test_non_manager_cannot_complete_a_stage(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    stage_id = _current_stage_id(client, admin_token, project["id"])
    member_id = create_org_user(client, admin_token, org_id, "member2@example.com", role="member")
    client.post(
        f"/api/v1/projects/{project['id']}/roles", json={"user_id": member_id, "role": "member"},
        headers=auth_headers(admin_token),
    )
    member_token = login(client, "member2@example.com", "Password123!")
    resp = client.post(
        f"/api/v1/projects/{project['id']}/stages/{stage_id}/complete",
        json={"cascade_to_requirements": False}, headers=auth_headers(member_token),
    )
    assert resp.status_code == 403


def test_completing_stage_with_cascade_completes_approved_requirements_targeting_it(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    stage_id = _current_stage_id(client, admin_token, project["id"])
    req = client.post(
        f"/api/v1/projects/{project['id']}/requirements",
        json={
            "name": "Cascaded req", "component_id": component_id, "category_id": category_id,
            "target_stage_id": stage_id,
        },
        headers=auth_headers(admin_token),
    ).json()
    client.put(
        f"/api/v1/projects/{project['id']}/requirements/{req['id']}",
        json={
            "name": req["name"], "component_id": component_id, "category_id": category_id,
            "owner_id": req["owner_id"], "status": "approved", "target_stage_id": stage_id,
        },
        headers=auth_headers(admin_token),
    )
    history_before = client.get(
        f"/api/v1/projects/{project['id']}/requirements/{req['id']}/history", headers=auth_headers(admin_token)
    ).json()

    resp = client.post(
        f"/api/v1/projects/{project['id']}/stages/{stage_id}/complete",
        json={"cascade_to_requirements": True}, headers=auth_headers(admin_token),
    )
    assert resp.status_code == 200

    resp = client.get(f"/api/v1/projects/{project['id']}/requirements/{req['id']}", headers=auth_headers(admin_token))
    body = resp.json()
    # C-G-11: the cascade sets the overlay directly, not a new version — the
    # requirement's status stays "approved" and its history doesn't grow.
    assert body["status"] == "approved"
    assert body["is_completed"] is True
    assert body["completed_at"] is not None
    assert body["completed_by"] is not None

    history_after = client.get(
        f"/api/v1/projects/{project['id']}/requirements/{req['id']}/history", headers=auth_headers(admin_token)
    ).json()
    assert len(history_after) == len(history_before)


def test_cascade_completion_is_still_gated_on_approved_status(client, admin_token, org_id):
    """A still-draft requirement targeting the stage is left untouched by
    the cascade — completion can only ever be set from an approved,
    unmodified-since state, same precondition `complete_requirement` itself
    enforces directly."""
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    stage_id = _current_stage_id(client, admin_token, project["id"])
    req = client.post(
        f"/api/v1/projects/{project['id']}/requirements",
        json={
            "name": "Still draft", "component_id": component_id, "category_id": category_id,
            "target_stage_id": stage_id,
        },
        headers=auth_headers(admin_token),
    ).json()

    resp = client.post(
        f"/api/v1/projects/{project['id']}/stages/{stage_id}/complete",
        json={"cascade_to_requirements": True}, headers=auth_headers(admin_token),
    )
    assert resp.status_code == 200

    resp = client.get(f"/api/v1/projects/{project['id']}/requirements/{req['id']}", headers=auth_headers(admin_token))
    assert resp.json()["is_completed"] is False


def test_completing_stage_without_cascade_leaves_requirements_uncompleted(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    stage_id = _current_stage_id(client, admin_token, project["id"])
    req = client.post(
        f"/api/v1/projects/{project['id']}/requirements",
        json={
            "name": "Not cascaded", "component_id": component_id, "category_id": category_id,
            "target_stage_id": stage_id,
        },
        headers=auth_headers(admin_token),
    ).json()
    client.put(
        f"/api/v1/projects/{project['id']}/requirements/{req['id']}",
        json={
            "name": req["name"], "component_id": component_id, "category_id": category_id,
            "owner_id": req["owner_id"], "status": "approved", "target_stage_id": stage_id,
        },
        headers=auth_headers(admin_token),
    )

    resp = client.post(
        f"/api/v1/projects/{project['id']}/stages/{stage_id}/complete",
        json={"cascade_to_requirements": False}, headers=auth_headers(admin_token),
    )
    assert resp.status_code == 200

    resp = client.get(f"/api/v1/projects/{project['id']}/requirements/{req['id']}", headers=auth_headers(admin_token))
    assert resp.json()["is_completed"] is False


def test_failed_review_outcome_clears_completion(client, admin_token, org_id):
    """C-G-11: "[a requirement marked completed] may later be reversed to
    non-compliant... when a review/audit occurs" — a `FAILED` review
    outcome recorded against a currently-completed requirement clears its
    completion overlay as part of recording that outcome."""
    from datetime import date, timedelta

    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    req = client.post(
        f"/api/v1/projects/{project['id']}/requirements",
        json={
            "name": "Reviewed then failed", "component_id": component_id, "category_id": category_id,
            "review_date": str(date.today() - timedelta(days=1)),
        },
        headers=auth_headers(admin_token),
    ).json()
    client.post(f"/api/v1/projects/{project['id']}/requirements/{req['id']}/approve", headers=auth_headers(admin_token))
    complete_resp = client.post(f"/api/v1/projects/{project['id']}/requirements/{req['id']}/complete", headers=auth_headers(admin_token))
    assert complete_resp.json()["is_completed"] is True

    resp = client.post(
        f"/api/v1/projects/{project['id']}/requirements/{req['id']}/reviews",
        json={"outcome": "failed", "comment": "No longer meets the updated standard."},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 201, resp.text

    updated = client.get(f"/api/v1/projects/{project['id']}/requirements/{req['id']}", headers=auth_headers(admin_token)).json()
    assert updated["is_completed"] is False
    assert updated["completed_at"] is None
    assert updated["completed_by"] is None
    # The requirement's lifecycle status is untouched by this — only the
    # overlay is cleared.
    assert updated["status"] == "approved"


def test_met_review_outcome_does_not_clear_completion(client, admin_token, org_id):
    """The completion overlay is only cleared on a FAILED outcome — a MET
    outcome recorded against a completed requirement leaves it completed."""
    from datetime import date, timedelta

    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    req = client.post(
        f"/api/v1/projects/{project['id']}/requirements",
        json={
            "name": "Reviewed and still met", "component_id": component_id, "category_id": category_id,
            "review_date": str(date.today() - timedelta(days=1)),
        },
        headers=auth_headers(admin_token),
    ).json()
    client.post(f"/api/v1/projects/{project['id']}/requirements/{req['id']}/approve", headers=auth_headers(admin_token))
    client.post(f"/api/v1/projects/{project['id']}/requirements/{req['id']}/complete", headers=auth_headers(admin_token))

    resp = client.post(
        f"/api/v1/projects/{project['id']}/requirements/{req['id']}/reviews",
        json={"outcome": "met"}, headers=auth_headers(admin_token),
    )
    assert resp.status_code == 201, resp.text

    updated = client.get(f"/api/v1/projects/{project['id']}/requirements/{req['id']}", headers=auth_headers(admin_token)).json()
    assert updated["is_completed"] is True
