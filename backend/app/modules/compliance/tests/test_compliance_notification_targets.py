"""Tests for the data Compliance notifications carry so they open their subject: a grant on a standard names the
standard, and a standard-level review (which has no project) names the standard instead of the review."""

from datetime import UTC, datetime, timedelta

from app.database import SessionLocal
from app.modules.compliance.tests.test_compliance_standards_api import _base
from app.modules.compliance.tests.test_project_compliance_api import _setup_published_standard_with_tree
from app.services.review_engine import send_review_reminders as send_review_due_notifications
from tests.conftest import auth_headers, create_org_user, login

TODAY = datetime.now(UTC).date()


def _of_type(client, token, notification_type: str) -> list[dict]:
    notifications = client.get("/api/v1/notifications", headers=auth_headers(token)).json()
    return [n for n in notifications if n["type"] == notification_type]


def test_a_standard_grant_names_the_standard(client, admin_token, org_id):
    standard, *_rest = _setup_published_standard_with_tree(client, admin_token, org_id)
    user_id = create_org_user(client, admin_token, org_id, "std-grantee@example.com", role="member")
    token = login(client, "std-grantee@example.com", "Password123!")
    resp = client.post(
        f"{_base(org_id)}/standards/{standard['id']}/members/{user_id}/roles",
        json={"role_key": "standards_contributor"}, headers=auth_headers(admin_token),
    )
    assert resp.status_code == 204, resp.text
    granted = _of_type(client, token, "permission_granted")
    assert granted and granted[0]["entity_type"] == "compliance_standard"
    assert granted[0]["entity_id"] == standard["id"]
    assert granted[0]["target_kinds"] == ["standard", "organization", "project"]


def test_a_standard_review_notification_names_the_standard(client, admin_token, org_id):
    standard, *_rest = _setup_published_standard_with_tree(client, admin_token, org_id)
    owner_id = create_org_user(client, admin_token, org_id, "std-review-owner@example.com", role="member")
    owner_token = login(client, "std-review-owner@example.com", "Password123!")
    created = client.post(
        f"{_base(org_id)}/standards/{standard['id']}/reviews",
        json={
            "frequency_label": "Annual", "next_due_date": (TODAY - timedelta(days=1)).isoformat(),
            "owner": {"type": "user", "id": owner_id},
        },
        headers=auth_headers(admin_token),
    )
    assert created.status_code == 201, created.text

    db = SessionLocal()
    try:
        send_review_due_notifications(db)
    finally:
        db.close()

    overdue = _of_type(client, owner_token, "compliance_review_overdue")
    assert overdue and overdue[0]["project_id"] is None
    assert overdue[0]["entity_type"] == "compliance_standard" and overdue[0]["entity_id"] == standard["id"]
    assert overdue[0]["target_kinds"] == ["project_compliance", "standard"]
