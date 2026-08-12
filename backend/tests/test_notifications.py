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


def test_stage_approval_notifies_other_project_members_but_not_the_approver(client, admin_token, org_id):
    """Regression test: `admin_token` is the one performing the transition
    (and, per `create_project`, already a project manager) — they must not
    be told about the very approval they just made, even though the
    broadcast is otherwise "every project member"."""
    project = create_project(client, admin_token, org_id)
    other_pm_id = create_org_user(client, admin_token, org_id, "stage-approval-pm2@example.com", role="member")
    client.post(
        f"/api/v1/projects/{project['id']}/roles", json={"user_id": other_pm_id, "role": "project_manager"},
        headers=auth_headers(admin_token),
    )
    other_pm_token = login(client, "stage-approval-pm2@example.com", "Password123!")

    stage_id = client.get(f"/api/v1/projects/{project['id']}/stages", headers=auth_headers(admin_token)).json()[0]["id"]
    client.post(
        f"/api/v1/projects/{project['id']}/stages/{stage_id}/transition?new_status=review",
        headers=auth_headers(admin_token),
    )
    client.post(
        f"/api/v1/projects/{project['id']}/stages/{stage_id}/transition?new_status=approved",
        headers=auth_headers(admin_token),
    )
    assert any(n["type"] == "stage_approved" for n in _notifications_for(client, other_pm_token))
    assert not any(n["type"] == "stage_approved" for n in _notifications_for(client, admin_token))


def test_change_request_submit_and_decide_notify_others_but_not_the_actor(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    requirement = client.post(
        f"/api/v1/projects/{project['id']}/requirements",
        json={"name": "Req", "component_id": component_id, "category_id": category_id},
        headers=auth_headers(admin_token),
    ).json()

    other_pm_id = create_org_user(client, admin_token, org_id, "cr-notify-pm2@example.com", role="member")
    client.post(
        f"/api/v1/projects/{project['id']}/roles", json={"user_id": other_pm_id, "role": "project_manager"},
        headers=auth_headers(admin_token),
    )
    other_pm_token = login(client, "cr-notify-pm2@example.com", "Password123!")
    stakeholder_id = create_org_user(client, admin_token, org_id, "cr-notify-stakeholder@example.com", role="member")
    client.post(
        f"/api/v1/projects/{project['id']}/roles", json={"user_id": stakeholder_id, "role": "stakeholder"},
        headers=auth_headers(admin_token),
    )
    stakeholder_token = login(client, "cr-notify-stakeholder@example.com", "Password123!")

    cr = client.post(
        f"/api/v1/projects/{project['id']}/change-requests",
        json={
            "kind": "modify_requirement", "requirement_id": requirement["id"], "changed_fields": ["name"],
            "proposed_name": "New name", "reason": "x",
        },
        headers=auth_headers(admin_token),
    ).json()
    client.post(f"/api/v1/projects/{project['id']}/change-requests/{cr['id']}/submit", headers=auth_headers(admin_token))

    # admin_token created and submitted this CR themselves, and is also a
    # project manager and (trivially) not a stakeholder — the submitted
    # notification must reach the *other* PM and the stakeholder, never the
    # submitter, who already knows they just submitted it.
    assert any(n["type"] == "change_request_submitted" for n in _notifications_for(client, other_pm_token))
    assert any(n["type"] == "stakeholder_input_requested" for n in _notifications_for(client, stakeholder_token))
    assert not any(n["type"] == "change_request_submitted" for n in _notifications_for(client, admin_token))

    client.post(
        f"/api/v1/projects/{project['id']}/change-requests/{cr['id']}/decide",
        json={"approve": True, "note": "ok"}, headers=auth_headers(admin_token),
    )
    # admin_token is both this CR's creator and the one deciding it — the
    # "your change request was approved" notification (aimed at the
    # creator) and the "requirements updated" broadcast must both skip them,
    # while the uninvolved other PM still gets the broadcast.
    admin_notifs = _notifications_for(client, admin_token)
    assert not any(n["type"] == "change_request_approved" for n in admin_notifs)
    assert not any(n["type"] == "requirements_updated" for n in admin_notifs)
    assert any(n["type"] == "requirements_updated" for n in _notifications_for(client, other_pm_token))


def test_change_request_approval_notifies_a_different_creator(client, admin_token, org_id):
    """Companion to the self-suppression test above: when the CR's creator
    genuinely isn't the person deciding it, they must still be notified —
    the fix only suppresses the case where they're the same person."""
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    requirement = client.post(
        f"/api/v1/projects/{project['id']}/requirements",
        json={"name": "Req", "component_id": component_id, "category_id": category_id},
        headers=auth_headers(admin_token),
    ).json()
    creator_id = create_org_user(client, admin_token, org_id, "cr-real-creator@example.com", role="member")
    client.post(
        f"/api/v1/projects/{project['id']}/roles", json={"user_id": creator_id, "role": "stakeholder"},
        headers=auth_headers(admin_token),
    )
    creator_token = login(client, "cr-real-creator@example.com", "Password123!")

    cr = client.post(
        f"/api/v1/projects/{project['id']}/change-requests",
        json={
            "kind": "modify_requirement", "requirement_id": requirement["id"], "changed_fields": ["name"],
            "proposed_name": "New name", "reason": "x",
        },
        headers=auth_headers(creator_token),
    ).json()
    client.post(f"/api/v1/projects/{project['id']}/change-requests/{cr['id']}/submit", headers=auth_headers(creator_token))
    client.post(
        f"/api/v1/projects/{project['id']}/change-requests/{cr['id']}/decide",
        json={"approve": True, "note": "ok"}, headers=auth_headers(admin_token),
    )
    assert any(n["type"] == "change_request_approved" for n in _notifications_for(client, creator_token))


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


def test_project_role_revoke_does_not_notify_a_self_revocation(client, admin_token, org_id):
    """A project manager can technically revoke their own role via the API
    (e.g. demoting themselves) — they must not be told "your role was
    revoked" about an action they just took deliberately."""
    project = create_project(client, admin_token, org_id)
    other_pm_id = create_org_user(client, admin_token, org_id, "revoke-self-pm2@example.com", role="member")
    client.post(
        f"/api/v1/projects/{project['id']}/roles", json={"user_id": other_pm_id, "role": "project_manager"},
        headers=auth_headers(admin_token),
    )
    my_id = client.get("/api/v1/auth/me", headers=auth_headers(admin_token)).json()["id"]
    resp = client.delete(
        f"/api/v1/projects/{project['id']}/roles/{my_id}/project_manager", headers=auth_headers(admin_token)
    )
    assert resp.status_code == 204
    assert not any(n["type"] == "permission_revoked" for n in _notifications_for(client, admin_token))


def test_project_role_revoke_still_notifies_someone_else(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    member_id = create_org_user(client, admin_token, org_id, "revoke-other-member@example.com", role="member")
    client.post(
        f"/api/v1/projects/{project['id']}/roles", json={"user_id": member_id, "role": "stakeholder"},
        headers=auth_headers(admin_token),
    )
    member_token = login(client, "revoke-other-member@example.com", "Password123!")
    client.delete(
        f"/api/v1/projects/{project['id']}/roles/{member_id}/stakeholder", headers=auth_headers(admin_token)
    )
    assert any(n["type"] == "permission_revoked" for n in _notifications_for(client, member_token))


def test_org_role_grant_does_not_notify_a_self_grant(client, admin_token, org_id):
    """Mirrors the project-role case above at the organisation level: an
    org admin granting themselves an additional role must not be told
    about it as if someone else had done it to them."""
    my_id = client.get("/api/v1/auth/me", headers=auth_headers(admin_token)).json()["id"]
    resp = client.post(
        f"/api/v1/orgs/{org_id}/users/{my_id}/roles", json={"user_id": my_id, "role": "project_creator"},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 204, resp.text
    assert not any(n["type"] == "permission_granted" for n in _notifications_for(client, admin_token))
