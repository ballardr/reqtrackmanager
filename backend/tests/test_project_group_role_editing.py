"""Tests for Phase 5 (project membership/groups redesign, docs/decisions.md):
`PATCH /projects/{id}/groups/{group_id}` (making a project group's role
editable after creation, C-U-11) and `DELETE /projects/{id}/groups/{group_id}`
(new) — the backend half of the Members/Groups page split.

`GET /projects/{id}/direct-members`, also added in that phase, was removed
in the follow-up UX batch's Phase D (2026-08-31, docs/decisions.md) once the
new unified Members table (built on `GET /effective-members`'s `direct_role`
provenance kind) made it a dead surface with no remaining frontend caller —
see `tests/test_project_group_role_editing.py`'s own history and `tests.
conftest.direct_project_roles` for the direct-DB-read replacement several of
this suite's assertions used to reach for it now use instead.

Both remaining mutating endpoints share `require_project_manage`'s gate tier
(same as `create_project_group`/`add_project_group_member`) and C-U-08's "a
project must always have at least one manager" guard with `remove_project_
group_member`/`revoke_project_role`.

Follow-up UX batch Phase C (2026-08-31, docs/decisions.md) removed the four
auto-created "standard" project groups and their `is_default` flag
entirely: `create_project`'s non-template path now grants the creator a
direct `PROJECT_MANAGER` `UserProjectRole` instead of adding them to a
default "Project Managers" group. Every test below that used to reach for
that default group via `_default_manager_group` now either uses the
creator's own direct grant directly, or — where a scenario specifically
needs an *existing group* to already be the project's sole manager source —
uses `_make_group_the_sole_manager` to set that up explicitly (grant a
second person the role via a brand-new group, then revoke the creator's own
direct grant, since a fresh project always has exactly one manager: the
creator, directly).
"""

from tests.conftest import auth_headers, create_org_user, create_project, login


def _make_group_the_sole_manager(client, admin_token, org_id, project_id) -> dict:
    """Creates a manager-role group with a *different* user as its only
    member, then revokes the project creator's own direct manager grant
    (C-U-10) — leaving the new group as the project's only manager source.

    `revoke_project_role`'s own C-U-08 guard only blocks removing a
    direct grant when the grantee would become the project's *sole*
    effective manager afterward (and isn't also an inherited manager) — so
    this only works cleanly because the new group's member is someone
    other than the creator: with two independent manager sources (the
    creator's direct grant, the new group), revoking the creator's direct
    grant leaves exactly one (the group), and the revoke itself is never
    blocked by the very guard this helper exists to set up a test for.
    """
    me = client.get("/api/v1/auth/me", headers=auth_headers(admin_token)).json()
    other_id = create_org_user(client, admin_token, org_id, "sole-manager-source@example.com", role="member")
    group = client.post(
        f"/api/v1/projects/{project_id}/groups", json={"name": "Managers", "role": "project_manager"},
        headers=auth_headers(admin_token),
    ).json()
    added = client.post(
        f"/api/v1/projects/{project_id}/groups/{group['id']}/members",
        json={"user_id": other_id}, headers=auth_headers(admin_token),
    )
    assert added.status_code == 204, added.text
    revoke = client.delete(
        f"/api/v1/projects/{project_id}/roles/{me['id']}/project_manager", headers=auth_headers(admin_token)
    )
    assert revoke.status_code == 204, revoke.text
    return group


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
    """C-U-08: PATCHing a group's role away from project_manager, with no
    backup manager source, must be rejected — here that group is set up as
    the project's *only* manager source via `_make_group_the_sole_manager`."""
    project = create_project(client, admin_token, org_id)
    manager_group = _make_group_the_sole_manager(client, admin_token, org_id, project["id"])

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
    manager_group = _make_group_the_sole_manager(client, admin_token, org_id, project["id"])

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


def test_group_response_has_no_is_default_field_and_delete_never_special_cases_it(client, admin_token, org_id):
    """`is_default` was removed from `ProjectGroup`/`ProjectGroupOut`
    entirely, and `delete_project_group` no longer special-cases it — the
    only remaining delete guard is C-U-08 ("a project must retain at least
    one manager"), which applies uniformly regardless of how a group came
    to exist. This project's creator already holds a direct
    PROJECT_MANAGER grant (C-U-10), so a brand-new manager-role group here
    is never the project's sole manager source and is freely deletable."""
    project = create_project(client, admin_token, org_id)
    group = client.post(
        f"/api/v1/projects/{project['id']}/groups", json={"name": "Extra Managers", "role": "project_manager"},
        headers=auth_headers(admin_token),
    ).json()
    assert "is_default" not in group

    resp = client.delete(
        f"/api/v1/projects/{project['id']}/groups/{group['id']}", headers=auth_headers(admin_token)
    )
    assert resp.status_code == 204, resp.text


def test_delete_custom_manager_group_blocked_when_sole_manager(client, admin_token, org_id):
    """C-U-08 on delete: a manager-role group can normally be deleted, but
    not if doing so would leave the project with zero managers."""
    project = create_project(client, admin_token, org_id)
    custom_group = _make_group_the_sole_manager(client, admin_token, org_id, project["id"])

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
    # me is manager via both their own direct grant (C-U-10) and
    # custom_group here, so deleting custom_group is safe.
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
    # Org admin of this project's own org, with no project role of their
    # own, can also reach the manage-tier-gated effective-members view
    # (`can_manage_project_settings`'s existing carve-out, C-U-01
    # clarification) — same tier `GET /direct-members` used to be gated at
    # before its removal (Phase D, follow-up UX batch, 2026-08-31).
    assert client.get(
        f"/api/v1/projects/{project['id']}/effective-members", headers=auth_headers(org_admin_token)
    ).status_code == 200
    assert client.delete(
        f"/api/v1/projects/{project['id']}/groups/{group['id']}", headers=auth_headers(org_admin_token)
    ).status_code == 204
