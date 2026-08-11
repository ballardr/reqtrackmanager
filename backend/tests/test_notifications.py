"""Tests for Pelion (v2) notifications (C-N-01..05): creation at the key
trigger points, the in-app notification centre, and per-type preferences.
Email delivery itself is exercised against the real MailHog service in the
Docker Compose stack (see docs/decisions.md) — these tests only verify a
Notification row is created and messages don't crash when SMTP is
unreachable (notify() swallows email delivery failures)."""

from tests.conftest import auth_headers, create_component_and_category, create_org_user, create_project, login


def _notifications_for(client, token):
    return client.get("/api/v1/notifications", headers=auth_headers(token)).json()


def test_password_change_creates_notification(client, admin_token):
    client.post(
        "/api/v1/auth/change-password",
        json={"current_password": "ChangeMe123!", "new_password": "NewPassword123!"},
        headers=auth_headers(admin_token),
    )
    new_token = login(client, "admin@example.com", "NewPassword123!")
    notifs = _notifications_for(client, new_token)
    assert any(n["type"] == "password_changed" for n in notifs)


def test_role_grant_creates_project_joined_notification(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    user_id = create_org_user(client, admin_token, org_id, "joiner@example.com", role="member")
    token = login(client, "joiner@example.com", "Password123!")

    client.post(
        f"/api/v1/projects/{project['id']}/roles", json={"user_id": user_id, "role": "stakeholder"},
        headers=auth_headers(admin_token),
    )
    notifs = _notifications_for(client, token)
    assert any(n["type"] == "project_joined" for n in notifs)


def test_stage_approval_notifies_project_members(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    stage_id = client.get(f"/api/v1/projects/{project['id']}/stages", headers=auth_headers(admin_token)).json()[0]["id"]
    client.post(
        f"/api/v1/projects/{project['id']}/stages/{stage_id}/transition?new_status=review",
        headers=auth_headers(admin_token),
    )
    client.post(
        f"/api/v1/projects/{project['id']}/stages/{stage_id}/transition?new_status=approved",
        headers=auth_headers(admin_token),
    )
    notifs = _notifications_for(client, admin_token)
    assert any(n["type"] == "stage_approved" for n in notifs)


def test_change_request_submit_and_decide_notify(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    requirement = client.post(
        f"/api/v1/projects/{project['id']}/requirements",
        json={"name": "Req", "component_id": component_id, "category_id": category_id},
        headers=auth_headers(admin_token),
    ).json()

    cr = client.post(
        f"/api/v1/projects/{project['id']}/change-requests",
        json={
            "kind": "modify_requirement", "requirement_id": requirement["id"], "changed_fields": ["name"],
            "proposed_name": "New name", "reason": "x",
        },
        headers=auth_headers(admin_token),
    ).json()
    client.post(f"/api/v1/projects/{project['id']}/change-requests/{cr['id']}/submit", headers=auth_headers(admin_token))

    notifs = _notifications_for(client, admin_token)
    assert any(n["type"] == "change_request_submitted" for n in notifs)

    client.post(
        f"/api/v1/projects/{project['id']}/change-requests/{cr['id']}/decide",
        json={"approve": True, "note": "ok"}, headers=auth_headers(admin_token),
    )
    notifs = _notifications_for(client, admin_token)
    assert any(n["type"] == "change_request_approved" for n in notifs)
    assert any(n["type"] == "requirements_updated" for n in notifs)


def test_mark_read_and_unread_filter(client, admin_token):
    unread = client.get("/api/v1/notifications?unread_only=true", headers=auth_headers(admin_token)).json()
    assert len(unread) == 0

    client.post(
        "/api/v1/auth/change-password",
        json={"current_password": "ChangeMe123!", "new_password": "NewPassword123!"},
        headers=auth_headers(admin_token),
    )
    token = login(client, "admin@example.com", "NewPassword123!")
    unread = client.get("/api/v1/notifications?unread_only=true", headers=auth_headers(token)).json()
    assert len(unread) == 1

    client.post(f"/api/v1/notifications/{unread[0]['id']}/read", headers=auth_headers(token))
    unread = client.get("/api/v1/notifications?unread_only=true", headers=auth_headers(token)).json()
    assert len(unread) == 0


def test_notification_preferences_default_and_update(client, admin_token):
    prefs = client.get("/api/v1/notifications/preferences", headers=auth_headers(admin_token)).json()
    assert all(p["ui_enabled"] and p["email_enabled"] for p in prefs)

    resp = client.put(
        "/api/v1/notifications/preferences/password_changed",
        json={"ui_enabled": False, "email_enabled": False},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 200
    prefs = client.get("/api/v1/notifications/preferences", headers=auth_headers(admin_token)).json()
    updated = next(p for p in prefs if p["type"] == "password_changed")
    assert updated["ui_enabled"] is False
    assert updated["email_enabled"] is False


def _trigger_password_changed_notifications(client, admin_token, count: int) -> str:
    """Password changes are an easy, always-available way to generate N
    distinct notifications for the same user in these tests without
    needing a project/org fixture per notification."""
    password = "ChangeMe123!"
    token = admin_token
    for i in range(count):
        new_password = f"Password{i}123!"
        client.post(
            "/api/v1/auth/change-password",
            json={"current_password": password, "new_password": new_password},
            headers=auth_headers(token),
        )
        token = login(client, "admin@example.com", new_password)
        password = new_password
    return token


def test_list_notifications_pagination(client, admin_token):
    token = _trigger_password_changed_notifications(client, admin_token, 3)

    resp = client.get("/api/v1/notifications?limit=2&offset=0", headers=auth_headers(token))
    assert resp.status_code == 200
    assert int(resp.headers["x-total-count"]) == 3
    page1 = resp.json()
    assert len(page1) == 2

    page2 = client.get("/api/v1/notifications?limit=2&offset=2", headers=auth_headers(token)).json()
    assert len(page2) == 1
    assert {n["id"] for n in page1} & {n["id"] for n in page2} == set()


def test_list_notifications_search(client, admin_token):
    token = _trigger_password_changed_notifications(client, admin_token, 1)

    matches = client.get("/api/v1/notifications?search=password", headers=auth_headers(token)).json()
    assert len(matches) >= 1

    no_matches = client.get(
        "/api/v1/notifications?search=nonexistent-search-term", headers=auth_headers(token)
    ).json()
    assert no_matches == []


def test_list_notifications_without_limit_is_unbounded(client, admin_token):
    token = _trigger_password_changed_notifications(client, admin_token, 2)
    resp = client.get("/api/v1/notifications", headers=auth_headers(token))
    assert resp.status_code == 200
    assert "x-total-count" not in resp.headers
    assert len(resp.json()) == 2
