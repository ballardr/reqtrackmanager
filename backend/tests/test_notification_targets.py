"""Tests for where a notification opens (`services.notification_targets`, `GET /notifications/{id}`).

Covers the guard that no registered notification type lacks a target kind, the kinds the API lists, the detail
endpoint (ownership, scope, whether the subject is still reachable), the email and digest links, and the ids the
organisation-level creation sites now carry. Each test builds its own users and projects.
"""

import uuid as uuid_lib
from unittest.mock import Mock, patch

from app.database import SessionLocal
from app.models.notification import Notification
from app.modules.registry import (
    get_all_notification_target_kinds,
    get_all_notification_targets,
    get_all_notification_types,
)
from app.services import notifications as notifications_module
from tests.conftest import auth_headers, create_org_user, create_project, login


def _mine(client, token) -> list[dict]:
    return client.get("/api/v1/notifications", headers=auth_headers(token)).json()


def _of_type(client, token, notification_type: str) -> list[dict]:
    return [n for n in _mine(client, token) if n["type"] == notification_type]


def _member(client, admin_token, org_id, prefix: str) -> tuple[str, str]:
    email = f"{prefix}-{uuid_lib.uuid4().hex[:8]}@example.com"
    user_id = create_org_user(client, admin_token, org_id, email, role="member")
    return user_id, login(client, email, "Password123!")


def test_every_notification_type_declares_a_target():
    """A type with no target would open nothing: each registered type (core and module) lists at least one kind."""
    targets = get_all_notification_targets()
    missing = sorted(key for key in get_all_notification_types() if not targets.get(key))
    assert missing == [], (
        f"Notification types with no target kind: {missing}. "
        "Declare one in services/notification_targets.py or on the owning module."
    )


def test_every_target_kind_is_in_the_vocabulary():
    """A kind the frontend cannot resolve is a dead link: every declared kind is core's or a module's registered one."""
    vocabulary = get_all_notification_target_kinds()
    unknown = {
        key: [kind for kind in kinds if kind not in vocabulary]
        for key, kinds in get_all_notification_targets().items()
        if any(kind not in vocabulary for kind in kinds)
    }
    assert unknown == {}


def test_no_target_is_declared_for_an_unregistered_type():
    """A typo in a target table would silently never apply."""
    stray = sorted(set(get_all_notification_targets()) - set(get_all_notification_types()))
    assert stray == []


def test_a_modules_more_specific_kind_comes_before_the_generic_one():
    """A grant on a standard opens the standard, an organisation grant the organisation, a project grant the project."""
    assert get_all_notification_targets()["permission_granted"] == ("standard", "organization", "project")


def test_the_list_carries_each_notifications_target_kinds(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    user_id, token = _member(client, admin_token, org_id, "joiner")
    client.post(
        f"/api/v1/projects/{project['id']}/roles", json={"user_id": user_id, "role": "stakeholder"},
        headers=auth_headers(admin_token),
    )
    joined = _of_type(client, token, "project_joined")
    assert joined and joined[0]["target_kinds"] == ["project"]


def test_the_detail_is_the_recipients_alone(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    user_id, token = _member(client, admin_token, org_id, "recipient")
    _other_id, other_token = _member(client, admin_token, org_id, "bystander")
    client.post(
        f"/api/v1/projects/{project['id']}/roles", json={"user_id": user_id, "role": "stakeholder"},
        headers=auth_headers(admin_token),
    )
    notification = _of_type(client, token, "project_joined")[0]

    own = client.get(f"/api/v1/notifications/{notification['id']}", headers=auth_headers(token))
    assert own.status_code == 200, own.text
    assert own.json()["subject_available"] is True
    assert own.json()["target_kinds"] == ["project"]

    assert client.get(f"/api/v1/notifications/{notification['id']}", headers=auth_headers(other_token)).status_code == 404
    assert client.get(f"/api/v1/notifications/{uuid_lib.uuid4()}", headers=auth_headers(token)).status_code == 404


def test_the_detail_says_when_access_to_the_subject_has_ended(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    user_id, token = _member(client, admin_token, org_id, "revoked")
    client.post(
        f"/api/v1/projects/{project['id']}/roles", json={"user_id": user_id, "role": "stakeholder"},
        headers=auth_headers(admin_token),
    )
    joined = _of_type(client, token, "project_joined")[0]
    assert client.get(f"/api/v1/notifications/{joined['id']}", headers=auth_headers(token)).json()["subject_available"] is True

    revoked = client.delete(f"/api/v1/projects/{project['id']}/roles/{user_id}/stakeholder", headers=auth_headers(admin_token))
    assert revoked.status_code == 204, revoked.text
    removal = _of_type(client, token, "permission_revoked")[0]
    assert removal["target_kinds"] == ["project"]
    detail = client.get(f"/api/v1/notifications/{removal['id']}", headers=auth_headers(token)).json()
    assert detail["subject_available"] is False


def test_the_fixed_notification_paths_are_not_read_as_an_id(client, admin_token):
    """`preferences` is registered before the id route, so it still answers as the preference list."""
    resp = client.get("/api/v1/notifications/preferences", headers=auth_headers(admin_token))
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_the_instant_email_opens_the_notification_detail(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    user_id, token = _member(client, admin_token, org_id, "mailed")
    with patch.object(notifications_module, "send_email", new=Mock()) as send:
        client.post(
            f"/api/v1/projects/{project['id']}/roles", json={"user_id": user_id, "role": "stakeholder"},
            headers=auth_headers(admin_token),
        )
    notification = _of_type(client, token, "project_joined")[0]
    assert send.called
    text_body = send.call_args.args[2]
    assert f"/notifications/{notification['id']}" in text_body
    assert f"/projects/{project['id']}" not in text_body


def test_a_notification_without_a_project_still_has_a_link_in_its_email(client, admin_token):
    with patch.object(notifications_module, "send_email", new=Mock()) as send:
        client.post(
            "/api/v1/auth/change-password",
            json={"current_password": "ChangeMe123!", "new_password": "NewPassword123!"},
            headers=auth_headers(admin_token),
        )
    token = login(client, "admin@example.com", "NewPassword123!")
    notification = _of_type(client, token, "password_changed")[0]
    assert f"/notifications/{notification['id']}" in send.call_args.args[2]


def test_the_digest_links_each_item(client, admin_token):
    import asyncio
    from unittest.mock import AsyncMock

    client.patch("/api/v1/auth/me/preferences", json={"email_digest_mode": "daily"}, headers=auth_headers(admin_token))
    client.post(
        "/api/v1/auth/change-password",
        json={"current_password": "ChangeMe123!", "new_password": "NewPassword123!"},
        headers=auth_headers(admin_token),
    )
    token = login(client, "admin@example.com", "NewPassword123!")
    notification = _of_type(client, token, "password_changed")[0]

    db = SessionLocal()
    try:
        with patch.object(notifications_module, "send_email_async", new=AsyncMock()) as send:
            asyncio.run(notifications_module.send_daily_digests(db))
        assert send.await_count == 1
        assert f"/notifications/{notification['id']}" in send.await_args.args[2]
        assert f"/notifications/{notification['id']}" in send.await_args.kwargs["html_body"]
    finally:
        db.close()


def test_an_organisation_role_grant_names_the_organisation(client, admin_token, org_id):
    user_id, token = _member(client, admin_token, org_id, "orggrant")
    resp = client.post(
        f"/api/v1/orgs/{org_id}/users/{user_id}/roles", json={"user_id": user_id, "role": "org_admin"}, headers=auth_headers(admin_token),
    )
    assert resp.status_code == 204, resp.text
    granted = _of_type(client, token, "permission_granted")
    assert granted and granted[0]["entity_type"] == "organization" and granted[0]["entity_id"] == org_id
    assert granted[0]["project_id"] is None
    detail = client.get(f"/api/v1/notifications/{granted[0]['id']}", headers=auth_headers(token)).json()
    assert detail["subject_available"] is True


def test_the_notification_row_id_is_known_before_the_email_is_sent(client, admin_token):
    """The email link is built from the row's id, so it is set when the row is created, not at flush."""
    db = SessionLocal()
    try:
        from app.models.user import User

        user = db.query(User).filter(User.email == "admin@example.com").one_or_none()
        assert user is not None
        created = notifications_module.notify(db, user, notification_type="password_changed", title="t")
        assert isinstance(created, Notification) and created.id is not None
        db.rollback()
    finally:
        db.close()
