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
    assert resp.json()["status"] == "completed"


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

    resp = client.post(
        f"/api/v1/projects/{project['id']}/stages/{stage_id}/complete",
        json={"cascade_to_requirements": True}, headers=auth_headers(admin_token),
    )
    assert resp.status_code == 200

    resp = client.get(f"/api/v1/projects/{project['id']}/requirements/{req['id']}", headers=auth_headers(admin_token))
    assert resp.json()["status"] == "completed"
