"""Tests for deleting an org group (`DELETE /orgs/{id}/groups/{group_id}`,
2026-10-05): cascade of memberships and the roles the group carried, audit
logging, tenant scoping and org-admin-only access, and that deleting a group
granting Project Manager never removes a project's real (floor-counted)
manager. The Compliance fallback-group block lives in that module's own
tests."""

from sqlalchemy import select

from app.database import SessionLocal
from app.models.audit import AuditEvent
from tests.conftest import auth_headers, create_org_admin_in, create_org_user, create_project, login


def _create_group(client, token, org_id, name):
    resp = client.post(f"/api/v1/orgs/{org_id}/groups", json={"name": name}, headers=auth_headers(token))
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _add_member(client, token, org_id, group_id, *, user_id=None, member_org_group_id=None):
    body = {"user_id": user_id} if user_id else {"member_org_group_id": member_org_group_id}
    resp = client.post(f"/api/v1/orgs/{org_id}/groups/{group_id}/members", json=body, headers=auth_headers(token))
    assert resp.status_code == 204, resp.text


def _grant(client, token, project_id, group_id, role):
    resp = client.post(f"/api/v1/projects/{project_id}/group-roles", json={"org_group_id": group_id, "role": role},
                       headers=auth_headers(token))
    assert resp.status_code in (200, 201, 204), resp.text


def _my_roles(client, token, project_id):
    """The caller's roles on a project; none once they've lost all access."""
    resp = client.get(f"/api/v1/projects/{project_id}/my-roles", headers=auth_headers(token))
    return resp.json()["roles"] if resp.status_code == 200 else []


def _group_ids(client, token, org_id):
    return {g["id"] for g in client.get(f"/api/v1/orgs/{org_id}/groups", headers=auth_headers(token)).json()}


def test_delete_removes_group_and_the_access_it_granted(client, admin_token):
    org, token = create_org_admin_in(client, admin_token, "Group Delete Co")
    project = create_project(client, token, org["id"], "Group Delete Project")
    member_id = create_org_user(client, token, org["id"], "group-delete-member@example.com")
    member = login(client, "group-delete-member@example.com", "Password123!")
    group_id = _create_group(client, token, org["id"], "Reviewers")
    _add_member(client, token, org["id"], group_id, user_id=member_id)
    _grant(client, token, project["id"], group_id, "stakeholder")
    assert "stakeholder" in _my_roles(client, member, project["id"])

    resp = client.delete(f"/api/v1/orgs/{org['id']}/groups/{group_id}", headers=auth_headers(token))
    assert resp.status_code == 204, resp.text
    assert group_id not in _group_ids(client, token, org["id"])
    assert "stakeholder" not in _my_roles(client, member, project["id"])

    db = SessionLocal()
    try:
        event = db.scalar(select(AuditEvent).where(AuditEvent.entity_id == group_id, AuditEvent.action == "deleted"))
        assert event is not None and event.entity_type == "org_group"
        assert event.detail["name"] == "Reviewers" and event.detail["member_count"] == 1
    finally:
        db.close()


def test_delete_is_org_admin_only_and_tenant_scoped(client, admin_token):
    org, token = create_org_admin_in(client, admin_token, "Group Delete Scope Co")
    group_id = _create_group(client, token, org["id"], "Scoped")
    create_org_user(client, token, org["id"], "group-delete-plain@example.com")
    plain = login(client, "group-delete-plain@example.com", "Password123!")
    assert client.delete(f"/api/v1/orgs/{org['id']}/groups/{group_id}", headers=auth_headers(plain)).status_code == 403

    other_org, other_token = create_org_admin_in(client, admin_token, "Group Delete Other Co")
    # Another org's admin can't reach it via their own org's path either.
    resp = client.delete(f"/api/v1/orgs/{other_org['id']}/groups/{group_id}", headers=auth_headers(other_token))
    assert resp.status_code == 404
    assert group_id in _group_ids(client, token, org["id"])


def test_deleting_a_manager_granting_group_keeps_the_projects_real_manager(client, admin_token):
    """Org-group-derived managers never count toward the C-U-08 floor
    (`rbac._direct_project_managers`), so a project always keeps a real
    manager and no floor check is needed: deleting a group that grants
    Project Manager (here through a nested group) removes only the members'
    group-derived role."""
    org, token = create_org_admin_in(client, admin_token, "Group Delete Manager Co")
    project = create_project(client, token, org["id"], "Group Managed")
    manager_id = create_org_user(client, token, org["id"], "group-delete-pm@example.com")
    manager = login(client, "group-delete-pm@example.com", "Password123!")
    outer = _create_group(client, token, org["id"], "Managers")
    inner = _create_group(client, token, org["id"], "Managers Inner")
    _add_member(client, token, org["id"], inner, user_id=manager_id)
    _add_member(client, token, org["id"], outer, member_org_group_id=inner)
    _grant(client, token, project["id"], outer, "project_manager")
    assert "project_manager" in _my_roles(client, manager, project["id"])
    # The creator's own direct grant is the floor and can't be revoked.
    me = client.get("/api/v1/auth/me", headers=auth_headers(token)).json()["id"]
    assert client.delete(f"/api/v1/projects/{project['id']}/roles/{me}/project_manager",
                         headers=auth_headers(token)).status_code == 400

    assert client.delete(f"/api/v1/orgs/{org['id']}/groups/{inner}", headers=auth_headers(token)).status_code == 204
    assert "project_manager" not in _my_roles(client, manager, project["id"])
    assert "project_manager" in _my_roles(client, token, project["id"])
