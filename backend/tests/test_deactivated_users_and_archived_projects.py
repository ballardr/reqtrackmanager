"""Tests for deactivated users and archived projects.

- No role or membership may be granted to a deactivated account: it could not use it, yet it would appear in
  member lists and as a manager or reviewer nobody can reach.
- Deactivating the sole manager of an *archived* project does not make the acting administrator its manager
  (the fallback is for live projects); the gap is audited instead.
"""

from sqlalchemy import select

from app.database import SessionLocal
from app.models.audit import AuditEvent
from app.models.project import UserProjectRole
from tests.conftest import auth_headers, create_org_admin_in, create_org_user, create_project


def _managers(project_id: str) -> set[str]:
    """User ids holding a direct `project_manager` role on the project."""
    db = SessionLocal()
    try:
        rows = db.scalars(select(UserProjectRole).where(UserProjectRole.project_id == project_id)).all()
        return {str(r.user_id) for r in rows if r.role.value == "project_manager"}
    finally:
        db.close()


def _deactivated_member(client, admin_token, name):
    """An organisation with its admin, a member who has been deactivated, and the admin's headers."""
    org, org_admin_token = create_org_admin_in(client, admin_token, name)
    headers = auth_headers(org_admin_token)
    email = f"{name.lower().replace(' ', '_')}_gone@example.com"
    user_id = create_org_user(client, org_admin_token, org["id"], email)
    assert client.post(f"/api/v1/orgs/{org['id']}/users/{user_id}/deactivate", headers=headers).status_code == 204
    return org, headers, user_id, email


def test_roles_and_memberships_cannot_be_granted_to_a_deactivated_user(client, admin_token):
    org, headers, user_id, email = _deactivated_member(client, admin_token, "Deactivated Grants")
    # Deactivation leaves the org role row, so the "member of the org" check alone would still pass.
    project = create_project(client, headers["Authorization"].split()[1], org["id"], name="Live Project")

    base, pid = f"/api/v1/orgs/{org['id']}", project["id"]
    refused = {
        "org role": client.post(f"{base}/users/{user_id}/roles", json={"user_id": user_id, "role": "project_creator"}, headers=headers),
        "project role": client.post(f"/api/v1/projects/{pid}/roles", json={"user_id": user_id, "role": "member"}, headers=headers),
        "by email": client.post(f"/api/v1/projects/{pid}/roles/by-email", json={"email": email, "role": "member"}, headers=headers),
    }
    group = client.post(f"/api/v1/orgs/{org['id']}/groups", json={"name": "Crew"}, headers=headers).json()
    refused["org group"] = client.post(
        f"/api/v1/orgs/{org['id']}/groups/{group['id']}/members", json={"user_id": user_id}, headers=headers,
    )
    for what, resp in refused.items():
        assert resp.status_code == 409, (what, resp.status_code, resp.text)
        assert "deactivated" in resp.json()["detail"]


def test_deactivating_the_sole_manager_of_an_archived_project_does_not_appoint_the_admin(client, admin_token):
    org, org_admin_token = create_org_admin_in(client, admin_token, "Archived Fallback")
    headers = auth_headers(org_admin_token)
    admin_id = client.get("/api/v1/auth/me", headers=headers).json()["id"]
    user_id = create_org_user(client, org_admin_token, org["id"], "archived_manager@example.com")

    projects = {}
    for name in ("Archived One", "Live One"):
        project = create_project(client, org_admin_token, org["id"], name=name)
        assert client.post(
            f"/api/v1/projects/{project['id']}/roles", json={"user_id": user_id, "role": "project_manager"}, headers=headers,
        ).status_code == 204
        # The admin created it, so hand management over to the member to make them the sole manager.
        assert client.delete(f"/api/v1/projects/{project['id']}/roles/{admin_id}/project_manager", headers=headers).status_code == 204
        projects[name] = project["id"]
    assert client.post(f"/api/v1/projects/{projects['Archived One']}/archive", headers=headers).status_code == 200

    assert client.post(f"/api/v1/orgs/{org['id']}/users/{user_id}/deactivate", headers=headers).status_code == 204

    assert _managers(projects["Archived One"]) == set()  # left dormant, not given to the acting admin
    assert _managers(projects["Live One"]) == {admin_id}  # a live project still gets the fallback manager
    db = SessionLocal()
    try:
        skipped = db.scalars(
            select(AuditEvent).where(AuditEvent.action == "manager_fallback_skipped_archived", AuditEvent.project_id == projects["Archived One"])
        ).all()
        assert len(skipped) == 1
    finally:
        db.close()

    # An organisation admin can still unarchive it and appoint someone.
    assert client.post(f"/api/v1/projects/{projects['Archived One']}/unarchive", headers=headers).status_code == 200
