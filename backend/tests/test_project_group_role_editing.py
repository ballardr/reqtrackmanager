"""Tests for Phase 5 (project membership/groups redesign, docs/decisions.md):
`PATCH /projects/{id}/groups/{group_id}` (making a project group's role
editable after creation, C-U-11), `DELETE /projects/{id}/groups/{group_id}`
(new), and `GET /projects/{id}/direct-members` (new) — the backend half of
the Members/Groups page split.

All three share `require_project_manage`'s gate tier (same as
`create_project_group`/`add_project_group_member`), and the two mutating
endpoints share C-U-08's "a project must always have at least one manager"
guard with `remove_project_group_member`/`revoke_project_role`.
"""

from tests.conftest import auth_headers, create_org_user, create_project, login


def _default_manager_group(client, admin_token, project_id) -> dict:
    groups = client.get(f"/api/v1/projects/{project_id}/groups", headers=auth_headers(admin_token)).json()
    return next(g for g in groups if g["role"] == "project_manager")


def test_update_group_role_reflected_live_with_no_membership_row_change(client, admin_token, org_id):
    """Happy path: PATCHing a group's role changes only `role` — its
    membership rows are untouched, and the new role is immediately what
    effective-role resolution sees, since it reads `ProjectGroup.role` live
    (no data migration/backfill needed for this to work on a pre-existing
    group)."""
    project = create_project(client, admin_token, org_id)
    member_id = create_org_user(client, admin_token, org_id, "reviewer1@example.com", role="member")
    group = client.post(
        f"/api/v1/projects/{project['id']}/groups", json={"name": "Reviewers", "role": "stakeholder"},
        headers=auth_headers(admin_token),
    ).json()
    client.post(
        f"/api/v1/projects/{project['id']}/groups/{group['id']}/members",
        json={"user_id": member_id}, headers=auth_headers(admin_token),
    )

    resp = client.patch(
        f"/api/v1/projects/{project['id']}/groups/{group['id']}", json={"role": "project_administrator"},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["role"] == "project_administrator"
    assert body["member_user_ids"] == [member_id]

    # Reflected live: the member's effective role changed with no new
    # ProjectGroupMember row and no re-add required.
    groups = client.get(f"/api/v1/projects/{project['id']}/groups", headers=auth_headers(admin_token)).json()
    reloaded = next(g for g in groups if g["id"] == group["id"])
    assert reloaded["role"] == "project_administrator"
    assert reloaded["member_user_ids"] == [member_id]


def test_update_group_role_no_op_when_role_unchanged(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    group = client.post(
        f"/api/v1/projects/{project['id']}/groups", json={"name": "Same Role", "role": "member"},
        headers=auth_headers(admin_token),
    ).json()
    resp = client.patch(
        f"/api/v1/projects/{project['id']}/groups/{group['id']}", json={"role": "member"},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 200
    assert resp.json()["role"] == "member"


def test_update_group_role_away_from_manager_blocked_when_sole_manager(client, admin_token, org_id):
    """C-U-08: the project's only manager source is the default "Project
    Managers" group (the creator's membership from project creation) — PATCHing
    its role away from project_manager, with no backup manager source, must
    be rejected."""
    project = create_project(client, admin_token, org_id)
    manager_group = _default_manager_group(client, admin_token, project["id"])

    resp = client.patch(
        f"/api/v1/projects/{project['id']}/groups/{manager_group['id']}", json={"role": "member"},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 400, resp.text

    # Rolled back entirely: the group's role is still project_manager.
    groups = client.get(f"/api/v1/projects/{project['id']}/groups", headers=auth_headers(admin_token)).json()
    reloaded = next(g for g in groups if g["id"] == manager_group["id"])
    assert reloaded["role"] == "project_manager"


def test_update_group_role_away_from_manager_allowed_with_backup_manager(client, admin_token, org_id):
    """The same change succeeds once a backup manager source exists — the
    guard re-checks *actual* effective managers after the change, not just
    whether this specific group used to grant it."""
    project = create_project(client, admin_token, org_id)
    me = client.get("/api/v1/auth/me", headers=auth_headers(admin_token)).json()
    manager_group = _default_manager_group(client, admin_token, project["id"])

    backup_group = client.post(
        f"/api/v1/projects/{project['id']}/groups", json={"name": "Backup Managers", "role": "project_manager"},
        headers=auth_headers(admin_token),
    ).json()
    client.post(
        f"/api/v1/projects/{project['id']}/groups/{backup_group['id']}/members",
        json={"user_id": me["id"]}, headers=auth_headers(admin_token),
    )

    resp = client.patch(
        f"/api/v1/projects/{project['id']}/groups/{manager_group['id']}", json={"role": "member"},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["role"] == "member"


def test_delete_default_group_is_rejected(client, admin_token, org_id):
    """C-U-10's four standard groups are never deletable, independent of
    C-U-08 — this project's default "Project Managers" group is also its
    only manager source, but the rejection reason is is_default, not the
    manager guard."""
    project = create_project(client, admin_token, org_id)
    manager_group = _default_manager_group(client, admin_token, project["id"])

    resp = client.delete(
        f"/api/v1/projects/{project['id']}/groups/{manager_group['id']}", headers=auth_headers(admin_token)
    )
    assert resp.status_code == 400, resp.text


def test_delete_custom_manager_group_blocked_when_sole_manager(client, admin_token, org_id):
    """C-U-08 on delete: a non-default manager-role group can normally be
    deleted, but not if doing so would leave the project with zero
    managers."""
    project = create_project(client, admin_token, org_id)
    me = client.get("/api/v1/auth/me", headers=auth_headers(admin_token)).json()
    manager_group = _default_manager_group(client, admin_token, project["id"])
    custom_group = client.post(
        f"/api/v1/projects/{project['id']}/groups", json={"name": "Custom Managers", "role": "project_manager"},
        headers=auth_headers(admin_token),
    ).json()
    client.post(
        f"/api/v1/projects/{project['id']}/groups/{custom_group['id']}/members",
        json={"user_id": me["id"]}, headers=auth_headers(admin_token),
    )
    # Move the only manager off the default group so custom_group is now the
    # sole manager source (this itself succeeds — backup existed at the time).
    demote = client.patch(
        f"/api/v1/projects/{project['id']}/groups/{manager_group['id']}", json={"role": "member"},
        headers=auth_headers(admin_token),
    )
    assert demote.status_code == 200, demote.text

    resp = client.delete(
        f"/api/v1/projects/{project['id']}/groups/{custom_group['id']}", headers=auth_headers(admin_token)
    )
    assert resp.status_code == 400, resp.text

    # Rolled back: the group (and its membership) still exists.
    groups = client.get(f"/api/v1/projects/{project['id']}/groups", headers=auth_headers(admin_token)).json()
    assert any(g["id"] == custom_group["id"] for g in groups)


def test_delete_custom_manager_group_allowed_with_backup_manager(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    me = client.get("/api/v1/auth/me", headers=auth_headers(admin_token)).json()
    custom_group = client.post(
        f"/api/v1/projects/{project['id']}/groups", json={"name": "Extra Managers", "role": "project_manager"},
        headers=auth_headers(admin_token),
    ).json()
    client.post(
        f"/api/v1/projects/{project['id']}/groups/{custom_group['id']}/members",
        json={"user_id": me["id"]}, headers=auth_headers(admin_token),
    )
    # me is manager via both the default group and custom_group here, so
    # deleting custom_group is safe.
    resp = client.delete(
        f"/api/v1/projects/{project['id']}/groups/{custom_group['id']}", headers=auth_headers(admin_token)
    )
    assert resp.status_code == 204, resp.text
    groups = client.get(f"/api/v1/projects/{project['id']}/groups", headers=auth_headers(admin_token)).json()
    assert not any(g["id"] == custom_group["id"] for g in groups)


def test_update_and_delete_group_gated_at_manage_tier(client, admin_token, org_id):
    """PATCH/DELETE 403 for a role below project-manage tier (a plain
    project member); success for an org admin of the project's own
    organisation who holds no project role at all, per
    `can_manage_project_settings`'s existing carve-out (C-U-01
    clarification) — verified to still apply to both new endpoints."""
    project = create_project(client, admin_token, org_id)
    group = client.post(
        f"/api/v1/projects/{project['id']}/groups", json={"name": "Gate Test", "role": "member"},
        headers=auth_headers(admin_token),
    ).json()

    plain_member_id = create_org_user(client, admin_token, org_id, "gate-member@example.com", role="member")
    client.post(
        f"/api/v1/projects/{project['id']}/roles", json={"user_id": plain_member_id, "role": "member"},
        headers=auth_headers(admin_token),
    )
    member_token = login(client, "gate-member@example.com", "Password123!")
    assert client.patch(
        f"/api/v1/projects/{project['id']}/groups/{group['id']}", json={"role": "stakeholder"},
        headers=auth_headers(member_token),
    ).status_code == 403
    assert client.delete(
        f"/api/v1/projects/{project['id']}/groups/{group['id']}", headers=auth_headers(member_token)
    ).status_code == 403

    # Org admin of this project's own org, with no direct/group project role.
    org_admin_id = create_org_user(client, admin_token, org_id, "gate-org-admin@example.com", role="org_admin")
    assert org_admin_id  # sanity: a real user id was returned
    org_admin_token = login(client, "gate-org-admin@example.com", "Password123!")
    assert client.patch(
        f"/api/v1/projects/{project['id']}/groups/{group['id']}", json={"role": "stakeholder"},
        headers=auth_headers(org_admin_token),
    ).status_code == 200
    assert client.get(
        f"/api/v1/projects/{project['id']}/direct-members", headers=auth_headers(org_admin_token)
    ).status_code == 200
    assert client.delete(
        f"/api/v1/projects/{project['id']}/groups/{group['id']}", headers=auth_headers(org_admin_token)
    ).status_code == 204


def test_direct_members_gated_at_view_or_manage_tier(client, admin_token, org_id):
    """`GET /direct-members` uses the same broader gate as
    `list_project_groups` (`require_project_view_or_manage`): any genuine
    project role is enough to view it (unlike PATCH/DELETE's stricter
    manage-tier gate), but a user with no role on the project at all — not
    even in the same organisation — still gets 403."""
    project = create_project(client, admin_token, org_id)
    non_member_id = create_org_user(client, admin_token, org_id, "no-project-role@example.com", role="member")
    assert non_member_id
    non_member_token = login(client, "no-project-role@example.com", "Password123!")
    assert client.get(
        f"/api/v1/projects/{project['id']}/direct-members", headers=auth_headers(non_member_token)
    ).status_code == 403

    plain_member_id = create_org_user(client, admin_token, org_id, "has-project-role@example.com", role="member")
    client.post(
        f"/api/v1/projects/{project['id']}/roles", json={"user_id": plain_member_id, "role": "member"},
        headers=auth_headers(admin_token),
    )
    member_token = login(client, "has-project-role@example.com", "Password123!")
    assert client.get(
        f"/api/v1/projects/{project['id']}/direct-members", headers=auth_headers(member_token)
    ).status_code == 200


def test_direct_members_returns_multi_role_array_per_user(client, admin_token, org_id):
    """A user holding two simultaneous direct role grants must appear as one
    row with both roles, not two rows or a collapsed single role — pins
    `UserProjectRole`'s real multiplicity (unique on (user_id, project_id,
    role), not one row per user)."""
    project = create_project(client, admin_token, org_id)
    user_id = create_org_user(client, admin_token, org_id, "multi-role@example.com", role="member")
    client.post(
        f"/api/v1/projects/{project['id']}/roles", json={"user_id": user_id, "role": "stakeholder"},
        headers=auth_headers(admin_token),
    )
    client.post(
        f"/api/v1/projects/{project['id']}/roles", json={"user_id": user_id, "role": "member"},
        headers=auth_headers(admin_token),
    )

    resp = client.get(f"/api/v1/projects/{project['id']}/direct-members", headers=auth_headers(admin_token))
    assert resp.status_code == 200, resp.text
    rows = resp.json()
    row = next(r for r in rows if r["user_id"] == user_id)
    assert set(row["roles"]) == {"stakeholder", "member"}
    assert row["email"] == "multi-role@example.com"

    # The project creator holds their manager role only via the default
    # group (ProjectGroupMember), never a direct UserProjectRole row from
    # project creation — so they must not appear here at all yet.
    me = client.get("/api/v1/auth/me", headers=auth_headers(admin_token)).json()
    assert not any(r["user_id"] == me["id"] for r in rows)
