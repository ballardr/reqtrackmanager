"""Tests for the mockup-driven engagement features: comment author display
name, comment reactions, per-entity subscriptions (with notification on new
comments), org advanced settings (SMTP/SSO storage), and project creation
with terminology/template flag set at creation time."""

from tests.conftest import (
    auth_headers,
    create_component_and_category,
    create_org_user,
    create_project,
    login,
)


def _create_requirement(client, admin_token, project_id, component_id, category_id):
    return client.post(
        f"/api/v1/projects/{project_id}/requirements",
        json={"name": "Engagement target", "component_id": component_id, "category_id": category_id},
        headers=auth_headers(admin_token),
    ).json()


def test_comment_includes_author_display_name(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    req = _create_requirement(client, admin_token, project["id"], component_id, category_id)

    posted = client.post(
        f"/api/v1/projects/{project['id']}/requirements/{req['id']}/comments",
        json={"body": "Looks good"}, headers=auth_headers(admin_token),
    )
    assert posted.status_code == 201, posted.text
    assert posted.json()["author_display_name"] == "Server Administrator"
    assert posted.json()["reaction_count"] == 0
    assert posted.json()["reacted_by_me"] is False


def test_comment_reaction_toggle(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    req = _create_requirement(client, admin_token, project["id"], component_id, category_id)
    comment = client.post(
        f"/api/v1/projects/{project['id']}/requirements/{req['id']}/comments",
        json={"body": "React to me"}, headers=auth_headers(admin_token),
    ).json()

    reacted = client.put(
        f"/api/v1/projects/{project['id']}/requirements/{req['id']}/comments/{comment['id']}/reaction",
        headers=auth_headers(admin_token),
    )
    assert reacted.status_code == 204

    listed = client.get(
        f"/api/v1/projects/{project['id']}/requirements/{req['id']}/comments", headers=auth_headers(admin_token)
    ).json()
    assert listed[0]["reaction_count"] == 1
    assert listed[0]["reacted_by_me"] is True

    # Reacting again is idempotent (still just 1), and unreacting removes it.
    client.put(
        f"/api/v1/projects/{project['id']}/requirements/{req['id']}/comments/{comment['id']}/reaction",
        headers=auth_headers(admin_token),
    )
    removed = client.delete(
        f"/api/v1/projects/{project['id']}/requirements/{req['id']}/comments/{comment['id']}/reaction",
        headers=auth_headers(admin_token),
    )
    assert removed.status_code == 204
    listed = client.get(
        f"/api/v1/projects/{project['id']}/requirements/{req['id']}/comments", headers=auth_headers(admin_token)
    ).json()
    assert listed[0]["reaction_count"] == 0
    assert listed[0]["reacted_by_me"] is False


def test_requirement_subscription_toggle_and_comment_notification(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    req = _create_requirement(client, admin_token, project["id"], component_id, category_id)

    subscriber_id = create_org_user(client, admin_token, org_id, "subscriber@example.com", role="member")
    client.post(
        f"/api/v1/projects/{project['id']}/roles", json={"user_id": subscriber_id, "role": "stakeholder"},
        headers=auth_headers(admin_token),
    )
    subscriber_token = login(client, "subscriber@example.com", "Password123!")

    fetched = client.get(
        f"/api/v1/projects/{project['id']}/requirements/{req['id']}", headers=auth_headers(subscriber_token)
    ).json()
    assert fetched["is_subscribed"] is False

    subscribed = client.put(
        f"/api/v1/projects/{project['id']}/requirements/{req['id']}/subscription",
        headers=auth_headers(subscriber_token),
    )
    assert subscribed.status_code == 204

    fetched = client.get(
        f"/api/v1/projects/{project['id']}/requirements/{req['id']}", headers=auth_headers(subscriber_token)
    ).json()
    assert fetched["is_subscribed"] is True

    # Someone else comments; the subscriber (not the commenter) gets notified.
    client.post(
        f"/api/v1/projects/{project['id']}/requirements/{req['id']}/comments",
        json={"body": "Update on this requirement"}, headers=auth_headers(admin_token),
    )
    notifications = client.get("/api/v1/notifications", headers=auth_headers(subscriber_token)).json()
    assert any(n["title"] == "New comment on a requirement you follow" for n in notifications)

    unsubscribed = client.delete(
        f"/api/v1/projects/{project['id']}/requirements/{req['id']}/subscription",
        headers=auth_headers(subscriber_token),
    )
    assert unsubscribed.status_code == 204
    fetched = client.get(
        f"/api/v1/projects/{project['id']}/requirements/{req['id']}", headers=auth_headers(subscriber_token)
    ).json()
    assert fetched["is_subscribed"] is False


def test_change_request_subscription_and_comment_notification(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    cr = client.post(
        f"/api/v1/projects/{project['id']}/change-requests",
        json={"kind": "new_requirement", "proposed_name": "x", "reason": "y"},
        headers=auth_headers(admin_token),
    ).json()

    subscriber_id = create_org_user(client, admin_token, org_id, "cr_subscriber@example.com", role="member")
    client.post(
        f"/api/v1/projects/{project['id']}/roles", json={"user_id": subscriber_id, "role": "stakeholder"},
        headers=auth_headers(admin_token),
    )
    subscriber_token = login(client, "cr_subscriber@example.com", "Password123!")

    client.put(
        f"/api/v1/projects/{project['id']}/change-requests/{cr['id']}/subscription",
        headers=auth_headers(subscriber_token),
    )
    client.post(
        f"/api/v1/projects/{project['id']}/change-requests/{cr['id']}/comments",
        json={"body": "Any update?"}, headers=auth_headers(admin_token),
    )
    notifications = client.get("/api/v1/notifications", headers=auth_headers(subscriber_token)).json()
    assert any(n["title"] == "New comment on a change request you follow" for n in notifications)


def test_org_advanced_settings_roundtrip_and_password_never_returned(client, admin_token, org_id):
    resp = client.put(
        f"/api/v1/orgs/{org_id}/advanced-settings",
        json={
            "smtp_host": "smtp.example.com", "smtp_port": 587, "smtp_username": "relay-user",
            "smtp_password": "super-secret", "smtp_use_tls": True,
            "sso_group_mappings": [{"sso_group": "engineering", "org_role": "member"}],
        },
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["smtp_host"] == "smtp.example.com"
    assert "smtp_password" not in resp.json()
    assert resp.json()["sso_group_mappings"] == [{"sso_group": "engineering", "org_role": "member"}]

    fetched = client.get(f"/api/v1/orgs/{org_id}/advanced-settings", headers=auth_headers(admin_token))
    assert fetched.status_code == 200
    assert fetched.json()["smtp_host"] == "smtp.example.com"
    assert "smtp_password" not in fetched.json()


def test_non_admin_cannot_read_advanced_settings(client, admin_token, org_id):
    create_org_user(client, admin_token, org_id, "settings_member@example.com", role="member")
    member_token = login(client, "settings_member@example.com", "Password123!")
    resp = client.get(f"/api/v1/orgs/{org_id}/advanced-settings", headers=auth_headers(member_token))
    assert resp.status_code == 403


def test_create_project_with_terminology_and_template_flag(client, admin_token, org_id):
    resp = client.post(
        "/api/v1/projects",
        json={
            "organization_id": org_id, "name": "Templated Project", "summary": "",
            "terminology": {"requirement": "Story"}, "is_template": True,
        },
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["terminology"] == {"requirement": "Story"}
    assert body["is_template"] is True


def test_create_project_rejects_unknown_terminology_key(client, admin_token, org_id):
    resp = client.post(
        "/api/v1/projects",
        json={"organization_id": org_id, "name": "Bad Terminology", "summary": "", "terminology": {"bogus": "x"}},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 422
