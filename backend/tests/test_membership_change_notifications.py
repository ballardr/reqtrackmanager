"""Tests for the "project members changed by someone who is not a project
manager" notification (docs/plans/platform-enhancements-2026-10-plan.md
Phase 2): an org admin / `grant_roles` holder editing a project's membership
without holding a manager role on it tells that project's managers.

Covers the trigger rule (non-manager actor only), every covered endpoint,
non-coverage of org-group-internal changes, inherited managers as recipients,
actor exclusion, coalescing and its line cap, preference opt-outs, and
cross-project recipient isolation. Each test builds its own project, so none
depends on state left by another.
"""

import uuid as uuid_lib
from types import SimpleNamespace
from unittest.mock import Mock, patch

from sqlalchemy import select

from app.database import SessionLocal
from app.models.enums import ProjectRole
from app.models.notification import Notification, NotificationType
from app.models.project import Project
from app.models.user import User
from app.services import invites as invites_module
from app.services.membership_notifications import (
    MAX_BODY_LINES,
    notify_managers_of_member_change,
)
from tests.conftest import auth_headers, create_org_user, create_project, login

TYPE = "project_members_changed_by_org"


def _uniq(prefix: str) -> str:
    return f"{prefix}-{uuid_lib.uuid4().hex[:8]}@example.com"


def _add_user(client, admin_token, org_id, prefix: str, role="member") -> tuple[str, str]:
    """Creates an org user; returns (user_id, token)."""
    email = _uniq(prefix)
    user_id = create_org_user(client, admin_token, org_id, email, role=role)
    return user_id, login(client, email, "Password123!")


def _grant(client, token, project_id, user_id, role):
    return client.post(
        f"/api/v1/projects/{project_id}/roles", json={"user_id": user_id, "role": role}, headers=auth_headers(token),
    )


def _mine(client, token) -> list[dict]:
    return [n for n in client.get("/api/v1/notifications", headers=auth_headers(token)).json() if n["type"] == TYPE]


def _managed_project_without_admin_as_manager(client, admin_token, org_id):
    """A project managed by a PM and a project administrator, with the org
    admin (`admin_token`, who `create_project` makes a manager) stripped of
    its own manager role — i.e. an org admin reaching in from outside."""
    project = create_project(client, admin_token, org_id, name=f"Proj {uuid_lib.uuid4().hex[:6]}")
    pm_id, pm_token = _add_user(client, admin_token, org_id, "pm")
    pa_id, pa_token = _add_user(client, admin_token, org_id, "pa")
    assert _grant(client, admin_token, project["id"], pm_id, "project_manager").status_code == 204
    assert _grant(client, admin_token, project["id"], pa_id, "project_administrator").status_code == 204
    admin_id = client.get("/api/v1/auth/me", headers=auth_headers(admin_token)).json()["id"]
    resp = client.delete(
        f"/api/v1/projects/{project['id']}/roles/{admin_id}/project_manager", headers=auth_headers(admin_token)
    )
    assert resp.status_code == 204, resp.text
    # Clear notifications produced by the setup itself.
    for token in (pm_token, pa_token):
        client.post("/api/v1/notifications/read-all", headers=auth_headers(token))
    return SimpleNamespace(project=project, pm_id=pm_id, pm_token=pm_token, pa_id=pa_id, pa_token=pa_token,
                           admin_id=admin_id)


def test_org_admin_direct_grant_notifies_managers_and_administrators_not_actor(client, admin_token, org_id):
    ctx = _managed_project_without_admin_as_manager(client, admin_token, org_id)
    target_id, _ = _add_user(client, admin_token, org_id, "target")

    assert _grant(client, admin_token, ctx.project["id"], target_id, "member").status_code == 204

    for token in (ctx.pm_token, ctx.pa_token):
        notes = _mine(client, token)
        assert len(notes) == 1
        assert notes[0]["project_id"] == ctx.project["id"]
        assert "Added" in notes[0]["body"] and "member" in notes[0]["body"]
    assert _mine(client, admin_token) == []


def test_project_manager_editing_own_project_does_not_notify(client, admin_token, org_id):
    ctx = _managed_project_without_admin_as_manager(client, admin_token, org_id)
    target_id, _ = _add_user(client, admin_token, org_id, "target")

    assert _grant(client, ctx.pm_token, ctx.project["id"], target_id, "member").status_code == 204

    assert _mine(client, ctx.pa_token) == []
    assert _mine(client, ctx.pm_token) == []


def test_org_admin_who_is_also_project_manager_does_not_notify(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)  # admin is PM here
    other_pm_id, other_pm_token = _add_user(client, admin_token, org_id, "pm2")
    _grant(client, admin_token, project["id"], other_pm_id, "project_manager")
    target_id, _ = _add_user(client, admin_token, org_id, "target")

    assert _grant(client, admin_token, project["id"], target_id, "member").status_code == 204

    assert _mine(client, other_pm_token) == []


def test_direct_revoke_notifies_managers(client, admin_token, org_id):
    ctx = _managed_project_without_admin_as_manager(client, admin_token, org_id)
    target_id, _ = _add_user(client, admin_token, org_id, "target")
    _grant(client, ctx.pm_token, ctx.project["id"], target_id, "member")

    resp = client.delete(
        f"/api/v1/projects/{ctx.project['id']}/roles/{target_id}/member", headers=auth_headers(admin_token)
    )
    assert resp.status_code == 204, resp.text

    notes = _mine(client, ctx.pm_token)
    assert len(notes) == 1 and "Removed" in notes[0]["body"]


def test_grant_roles_only_holder_notifies_managers(client, admin_token, org_id):
    ctx = _managed_project_without_admin_as_manager(client, admin_token, org_id)
    holder_id, holder_token = _add_user(client, admin_token, org_id, "granter")
    role = client.post(
        f"/api/v1/orgs/{org_id}/custom-roles",
        json={"name": f"Granter {uuid_lib.uuid4().hex[:6]}", "description": "", "scope": "org",
              "permissions": ["grant_roles"]},
        headers=auth_headers(admin_token),
    ).json()
    assert client.post(
        f"/api/v1/orgs/{org_id}/custom-roles/{role['id']}/users/{holder_id}", json={},
        headers=auth_headers(admin_token),
    ).status_code == 204
    target_id, _ = _add_user(client, admin_token, org_id, "target")

    assert _grant(client, holder_token, ctx.project["id"], target_id, "member").status_code == 204

    assert len(_mine(client, ctx.pm_token)) == 1


def _create_org_group(client, admin_token, org_id) -> str:
    return client.post(
        f"/api/v1/orgs/{org_id}/groups", json={"name": f"G {uuid_lib.uuid4().hex[:6]}"},
        headers=auth_headers(admin_token),
    ).json()["id"]


def test_direct_org_group_grant_and_revoke_notify_managers(client, admin_token, org_id):
    ctx = _managed_project_without_admin_as_manager(client, admin_token, org_id)
    group_id = _create_org_group(client, admin_token, org_id)

    grant = client.post(
        f"/api/v1/projects/{ctx.project['id']}/group-roles",
        json={"org_group_id": group_id, "role": "stakeholder"}, headers=auth_headers(admin_token),
    )
    assert grant.status_code == 204, grant.text
    revoke = client.delete(
        f"/api/v1/projects/{ctx.project['id']}/group-roles/{group_id}/stakeholder", headers=auth_headers(admin_token)
    )
    assert revoke.status_code == 204, revoke.text

    notes = _mine(client, ctx.pm_token)
    assert len(notes) == 1  # coalesced
    assert "Added group" in notes[0]["body"] and "Removed group" in notes[0]["body"]


def test_project_group_role_grant_and_revoke_notify_managers(client, admin_token, org_id):
    ctx = _managed_project_without_admin_as_manager(client, admin_token, org_id)
    group = client.post(
        f"/api/v1/projects/{ctx.project['id']}/groups", json={"name": "Reviewers"}, headers=auth_headers(admin_token),
    ).json()

    grant = client.post(
        f"/api/v1/projects/{ctx.project['id']}/groups/{group['id']}/roles",
        json={"role": "member"}, headers=auth_headers(admin_token),
    )
    assert grant.status_code == 204, grant.text
    revoke = client.delete(
        f"/api/v1/projects/{ctx.project['id']}/groups/{group['id']}/roles/member", headers=auth_headers(admin_token)
    )
    assert revoke.status_code == 204, revoke.text

    body = _mine(client, ctx.pm_token)[0]["body"]
    assert "Added project group Reviewers" in body and "Removed project group Reviewers" in body


def test_by_email_invite_notifies_managers(client, admin_token, org_id):
    ctx = _managed_project_without_admin_as_manager(client, admin_token, org_id)
    assert client.put(
        f"/api/v1/orgs/{org_id}/advanced-settings",
        json={"external_user_policy": "anyone", "auto_accept_email_domain": None}, headers=auth_headers(admin_token),
    ).status_code == 200
    invitee = _uniq("invitee")

    with patch.object(invites_module, "send_email", new=Mock()):
        resp = client.post(
            f"/api/v1/projects/{ctx.project['id']}/roles/by-email", json={"email": invitee, "role": "member"},
            headers=auth_headers(admin_token),
        )
    assert resp.status_code == 200, resp.text

    notes = _mine(client, ctx.pm_token)
    assert len(notes) == 1 and f"Invited {invitee}" in notes[0]["body"]


def test_org_group_membership_change_does_not_notify(client, admin_token, org_id):
    """The intended mechanism per the plan: editing who is *inside* an org
    group is not a project member edit and must stay silent."""
    ctx = _managed_project_without_admin_as_manager(client, admin_token, org_id)
    group_id = _create_org_group(client, admin_token, org_id)
    client.post(
        f"/api/v1/projects/{ctx.project['id']}/group-roles",
        json={"org_group_id": group_id, "role": "member"}, headers=auth_headers(ctx.pm_token),
    )
    member_id, _ = _add_user(client, admin_token, org_id, "ingroup")

    resp = client.post(
        f"/api/v1/orgs/{org_id}/groups/{group_id}/members", json={"user_id": member_id},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code in (200, 201, 204), resp.text

    assert _mine(client, ctx.pm_token) == []


def test_inherited_manager_receives_notification(client, admin_token, org_id):
    parent_pm_id, parent_pm_token = _add_user(client, admin_token, org_id, "parentpm")
    parent = create_project(client, admin_token, org_id, name=f"Parent {uuid_lib.uuid4().hex[:6]}", can_be_parent=True)
    _grant(client, admin_token, parent["id"], parent_pm_id, "project_manager")
    admin_id = client.get("/api/v1/auth/me", headers=auth_headers(admin_token)).json()["id"]
    # The org admin created both projects, so it would otherwise stay a manager of the child by inheritance.
    assert client.delete(
        f"/api/v1/projects/{parent['id']}/roles/{admin_id}/project_manager", headers=auth_headers(admin_token)
    ).status_code == 204
    child = create_project(
        client, admin_token, org_id, name=f"Child {uuid_lib.uuid4().hex[:6]}", parent_project_id=parent["id"],
        role_inheritance_mode="mirror_role", role_inheritance_filter_role="project_manager",
    )
    child_pm_id, _ = _add_user(client, admin_token, org_id, "childpm")
    _grant(client, admin_token, child["id"], child_pm_id, "project_manager")
    assert client.delete(
        f"/api/v1/projects/{child['id']}/roles/{admin_id}/project_manager", headers=auth_headers(admin_token)
    ).status_code == 204
    client.post("/api/v1/notifications/read-all", headers=auth_headers(parent_pm_token))
    target_id, _ = _add_user(client, admin_token, org_id, "target")

    assert _grant(client, admin_token, child["id"], target_id, "member").status_code == 204

    notes = [n for n in _mine(client, parent_pm_token) if n["project_id"] == child["id"]]
    assert len(notes) == 1


def test_repeated_changes_by_same_actor_coalesce_into_one_notification(client, admin_token, org_id):
    ctx = _managed_project_without_admin_as_manager(client, admin_token, org_id)
    first_id, _ = _add_user(client, admin_token, org_id, "first")
    second_id, _ = _add_user(client, admin_token, org_id, "second")

    _grant(client, admin_token, ctx.project["id"], first_id, "member")
    _grant(client, admin_token, ctx.project["id"], second_id, "stakeholder")

    notes = _mine(client, ctx.pm_token)
    assert len(notes) == 1
    lines = notes[0]["body"].split("\n")
    assert len(lines) == 2 and "member" in lines[0] and "stakeholder" in lines[1]


def test_read_notification_is_not_coalesced_into(client, admin_token, org_id):
    ctx = _managed_project_without_admin_as_manager(client, admin_token, org_id)
    first_id, _ = _add_user(client, admin_token, org_id, "first")
    second_id, _ = _add_user(client, admin_token, org_id, "second")
    _grant(client, admin_token, ctx.project["id"], first_id, "member")
    client.post("/api/v1/notifications/read-all", headers=auth_headers(ctx.pm_token))

    _grant(client, admin_token, ctx.project["id"], second_id, "member")

    assert len(_mine(client, ctx.pm_token)) == 2


def test_coalesced_body_is_capped(client, admin_token, org_id):
    ctx = _managed_project_without_admin_as_manager(client, admin_token, org_id)
    db = SessionLocal()
    try:
        project = db.get(Project, uuid_lib.UUID(ctx.project["id"]))
        actor = db.get(User, uuid_lib.UUID(ctx.admin_id))
        for i in range(MAX_BODY_LINES + 5):
            notify_managers_of_member_change(
                db, project=project, actor=actor, verb="Added", target=f"user {i}", role=ProjectRole.MEMBER,
            )
        db.commit()
        rows = db.scalars(
            select(Notification).where(
                Notification.user_id == uuid_lib.UUID(ctx.pm_id),
                Notification.type == NotificationType.PROJECT_MEMBERS_CHANGED_BY_ORG,
            )
        ).all()
        assert len(rows) == 1
        lines = rows[0].body.split("\n")
        assert len(lines) == MAX_BODY_LINES + 1 and lines[-1].startswith("…")
    finally:
        db.close()


def test_ui_opt_out_hides_notification(client, admin_token, org_id):
    ctx = _managed_project_without_admin_as_manager(client, admin_token, org_id)
    resp = client.put(
        f"/api/v1/notifications/preferences/{TYPE}", json={"ui_enabled": False, "email_enabled": False},
        headers=auth_headers(ctx.pm_token),
    )
    assert resp.status_code == 200, resp.text
    target_id, _ = _add_user(client, admin_token, org_id, "target")

    _grant(client, admin_token, ctx.project["id"], target_id, "member")

    assert _mine(client, ctx.pm_token) == []
    assert len(_mine(client, ctx.pa_token)) == 1  # opt-out is per recipient


def test_managers_of_other_projects_are_not_notified(client, admin_token, org_id):
    ctx = _managed_project_without_admin_as_manager(client, admin_token, org_id)
    other = _managed_project_without_admin_as_manager(client, admin_token, org_id)
    target_id, _ = _add_user(client, admin_token, org_id, "target")

    _grant(client, admin_token, ctx.project["id"], target_id, "member")

    assert len(_mine(client, ctx.pm_token)) == 1
    assert _mine(client, other.pm_token) == []
    assert _mine(client, other.pa_token) == []


def test_ui_opt_out_for_any_type_is_honoured_by_notification_list(client, admin_token, org_id):
    """Regression: `ui_enabled=False` was stored but never applied by the
    list endpoint, so an in-app opt-out had no effect."""
    project = create_project(client, admin_token, org_id)
    user_id, token = _add_user(client, admin_token, org_id, "optout")
    client.put(
        "/api/v1/notifications/preferences/project_joined", json={"ui_enabled": False, "email_enabled": True},
        headers=auth_headers(token),
    )

    _grant(client, admin_token, project["id"], user_id, "member")

    assert not any(
        n["type"] == "project_joined" for n in client.get("/api/v1/notifications", headers=auth_headers(token)).json()
    )


def _create_project_group(client, token, project_id, name="QA") -> str:
    resp = client.post(f"/api/v1/projects/{project_id}/groups", json={"name": name}, headers=auth_headers(token))
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def test_project_group_member_add_remove_and_delete_notify_managers(client, admin_token, org_id):
    """An org admin outside the project can edit a project group (the gate
    admits org admins), so each of those edits must reach the managers."""
    ctx = _managed_project_without_admin_as_manager(client, admin_token, org_id)
    group_id = _create_project_group(client, admin_token, ctx.project["id"], name="QA")
    user_id, _ = _add_user(client, admin_token, org_id, "grpmember")
    org_group_id = _create_org_group(client, admin_token, org_id)
    base = f"/api/v1/projects/{ctx.project['id']}/groups/{group_id}"

    assert client.post(f"{base}/members", json={"user_id": user_id}, headers=auth_headers(admin_token)).status_code == 204
    assert client.post(
        f"{base}/members", json={"org_group_id": org_group_id}, headers=auth_headers(admin_token)
    ).status_code == 204
    assert client.delete(f"{base}/members/{user_id}", headers=auth_headers(admin_token)).status_code == 204
    assert client.delete(
        f"/api/v1/projects/{ctx.project['id']}/groups/{group_id}", headers=auth_headers(admin_token)
    ).status_code == 204

    notes = _mine(client, ctx.pm_token)
    assert len(notes) == 1  # coalesced
    body = notes[0]["body"]
    assert "to project group QA" in body and "group G " in body
    assert "Removed grpmember" in body and "from project group QA" in body
    assert "Deleted project group QA" in body
    assert _mine(client, admin_token) == []


def test_project_manager_editing_project_group_does_not_notify(client, admin_token, org_id):
    ctx = _managed_project_without_admin_as_manager(client, admin_token, org_id)
    group_id = _create_project_group(client, ctx.pm_token, ctx.project["id"])
    user_id, _ = _add_user(client, admin_token, org_id, "grpmember")

    resp = client.post(
        f"/api/v1/projects/{ctx.project['id']}/groups/{group_id}/members", json={"user_id": user_id},
        headers=auth_headers(ctx.pm_token),
    )
    assert resp.status_code == 204, resp.text

    assert _mine(client, ctx.pa_token) == []
