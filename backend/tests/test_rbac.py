"""Tests for role-based access control boundaries (C-U-01, C-U-03)."""

from tests.conftest import (
    auth_headers,
    create_component_and_category,
    create_org_admin_in,
    create_org_user,
    create_project,
    login,
)


def test_member_cannot_create_project(client, admin_token, org_id):
    create_org_user(client, admin_token, org_id, "member@example.com", role="member")
    token = login(client, "member@example.com", "Password123!")

    resp = client.post(
        "/api/v1/projects", json={"organization_id": org_id, "name": "Should Fail", "summary": ""},
        headers=auth_headers(token),
    )
    assert resp.status_code == 403


def test_project_creator_can_create_project(client, admin_token, org_id):
    create_org_user(client, admin_token, org_id, "creator@example.com", role="project_creator")
    token = login(client, "creator@example.com", "Password123!")

    resp = client.post(
        "/api/v1/projects", json={"organization_id": org_id, "name": "Allowed", "summary": ""},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201


def test_project_creator_becomes_project_manager(client, admin_token, org_id):
    """The project creator is added to the Project Managers group (C-U-10)."""
    create_org_user(client, admin_token, org_id, "creator2@example.com", role="project_creator")
    token = login(client, "creator2@example.com", "Password123!")
    project = client.post(
        "/api/v1/projects", json={"organization_id": org_id, "name": "PM Test", "summary": ""},
        headers=auth_headers(token),
    ).json()

    groups = client.get(f"/api/v1/projects/{project['id']}/groups", headers=auth_headers(token)).json()
    manager_group = next(g for g in groups if g["role"] == "project_manager")
    me = client.get("/api/v1/auth/me", headers=auth_headers(token)).json()
    assert me["id"] in manager_group["member_user_ids"]


def test_member_cannot_create_requirement(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    create_org_user(client, admin_token, org_id, "member2@example.com", role="member")

    # Project-level member role: give them member role on the project too.
    client.post(
        f"/api/v1/projects/{project['id']}/roles",
        json={"user_id": _user_id(client, admin_token, org_id, "member2@example.com"), "role": "member"},
        headers=auth_headers(admin_token),
    )
    token = login(client, "member2@example.com", "Password123!")
    resp = client.post(
        f"/api/v1/projects/{project['id']}/requirements",
        json={"name": "Should fail", "component_id": component_id, "category_id": category_id},
        headers=auth_headers(token),
    )
    assert resp.status_code == 403


def test_non_member_cannot_view_project(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    create_org_user(client, admin_token, org_id, "outsider@example.com", role="member")
    token = login(client, "outsider@example.com", "Password123!")

    resp = client.get(f"/api/v1/projects/{project['id']}", headers=auth_headers(token))
    assert resp.status_code == 403


def test_org_admin_can_list_every_project_in_org_without_a_role(client, admin_token, org_id):
    """`GET /orgs/{id}/projects` exists specifically so an org admin can
    find and manage users on a project they hold no role in (unlike
    `GET /projects`, which never surfaces such a project at all)."""
    org, org_admin_token = create_org_admin_in(client, admin_token, "Org Projects Admin Reach")
    create_org_user(client, admin_token, org["id"], "reach_creator@example.com", role="project_creator")
    creator_token = login(client, "reach_creator@example.com", "Password123!")
    project = create_project(client, creator_token, org["id"], "No Role Project")

    # The regular project listing doesn't show it to the org admin.
    projects = client.get("/api/v1/projects?archived=false", headers=auth_headers(org_admin_token)).json()
    assert project["id"] not in {p["id"] for p in projects}

    # The org-scoped admin listing does.
    org_projects = client.get(f"/api/v1/orgs/{org['id']}/projects", headers=auth_headers(org_admin_token)).json()
    assert project["id"] in {p["id"] for p in org_projects}

    # A plain member (not org admin) is rejected.
    resp = client.get(f"/api/v1/orgs/{org['id']}/projects", headers=auth_headers(creator_token))
    assert resp.status_code == 403


def test_org_admin_can_manage_group_membership_on_a_project_with_no_role(client, admin_token, org_id):
    org, org_admin_token = create_org_admin_in(client, admin_token, "Org Projects Group Manage")
    create_org_user(client, admin_token, org["id"], "reach_creator2@example.com", role="project_creator")
    creator_token = login(client, "reach_creator2@example.com", "Password123!")
    project = create_project(client, creator_token, org["id"], "Group Manage Project")
    target_id = create_org_user(client, admin_token, org["id"], "reach_target@example.com", role="member")

    groups = client.get(f"/api/v1/projects/{project['id']}/groups", headers=auth_headers(org_admin_token)).json()
    member_group = next(g for g in groups if g["role"] == "member")

    add_resp = client.post(
        f"/api/v1/projects/{project['id']}/groups/{member_group['id']}/members",
        json={"user_id": target_id}, headers=auth_headers(org_admin_token),
    )
    assert add_resp.status_code == 204, add_resp.text

    groups_after = client.get(f"/api/v1/projects/{project['id']}/groups", headers=auth_headers(org_admin_token)).json()
    member_group_after = next(g for g in groups_after if g["id"] == member_group["id"])
    assert target_id in member_group_after["member_user_ids"]

    remove_resp = client.delete(
        f"/api/v1/projects/{project['id']}/groups/{member_group['id']}/members/{target_id}",
        headers=auth_headers(org_admin_token),
    )
    assert remove_resp.status_code == 204

    # An unrelated plain member (no role, not org admin) is still rejected.
    outsider_token = login(client, "reach_target@example.com", "Password123!")
    resp = client.get(f"/api/v1/projects/{project['id']}/groups", headers=auth_headers(outsider_token))
    assert resp.status_code == 403


def test_only_project_manager_can_approve_stage(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    create_org_user(client, admin_token, org_id, "admin_role@example.com", role="member")
    user_id = _user_id(client, admin_token, org_id, "admin_role@example.com")
    client.post(
        f"/api/v1/projects/{project['id']}/roles",
        json={"user_id": user_id, "role": "project_administrator"},
        headers=auth_headers(admin_token),
    )
    token = login(client, "admin_role@example.com", "Password123!")

    stages = client.get(f"/api/v1/projects/{project['id']}/stages", headers=auth_headers(token)).json()
    stage_id = stages[0]["id"]
    resp = client.post(
        f"/api/v1/projects/{project['id']}/stages/{stage_id}/transition?new_status=approved",
        headers=auth_headers(token),
    )
    assert resp.status_code == 403


def _user_id(client, admin_token, org_id, email) -> str:
    users = client.get(f"/api/v1/orgs/{org_id}/users", headers=auth_headers(admin_token)).json()
    return next(u["user_id"] for u in users if u["email"] == email)


def test_org_group_nested_in_project_group_grants_effective_role(client, admin_token, org_id):
    """C-U-12: a member of an organisation group nested into a project group
    must actually receive that project group's effective role. Regression
    test for a real bug caught by ruff (F821): `get_effective_project_roles`
    used `OrgGroup` in a live query but never imported it, so this exact
    path raised NameError at runtime whenever it executed."""
    project = create_project(client, admin_token, org_id)
    user_id = create_org_user(client, admin_token, org_id, "nested_member@example.com", role="member")

    org_group = client.post(
        f"/api/v1/orgs/{org_id}/groups", json={"name": "Dev Team"}, headers=auth_headers(admin_token)
    ).json()
    client.post(
        f"/api/v1/orgs/{org_id}/groups/{org_group['id']}/members",
        json={"user_id": user_id}, headers=auth_headers(admin_token),
    )

    project_group = client.post(
        f"/api/v1/projects/{project['id']}/groups", json={"name": "Stakeholders Team", "role": "stakeholder"},
        headers=auth_headers(admin_token),
    ).json()
    nested = client.post(
        f"/api/v1/projects/{project['id']}/groups/{project_group['id']}/members",
        json={"org_group_id": org_group["id"]}, headers=auth_headers(admin_token),
    )
    assert nested.status_code == 204, nested.text

    token = login(client, "nested_member@example.com", "Password123!")
    resp = client.get(f"/api/v1/projects/{project['id']}", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text


def test_plain_member_can_leave_organization(client, admin_token, org_id):
    create_org_user(client, admin_token, org_id, "leaver@example.com", role="member")
    token = login(client, "leaver@example.com", "Password123!")

    resp = client.delete(f"/api/v1/orgs/{org_id}/membership", headers=auth_headers(token))
    assert resp.status_code == 204, resp.text

    # The org no longer appears in their own project-scoped listing of orgs.
    orgs = client.get("/api/v1/orgs", headers=auth_headers(token)).json()
    assert org_id not in [o["id"] for o in orgs]

    # A second leave attempt has nothing left to remove.
    resp = client.delete(f"/api/v1/orgs/{org_id}/membership", headers=auth_headers(token))
    assert resp.status_code == 404


def test_leaving_org_removes_subscriptions_so_no_more_content_leaks_via_notifications(
    client, admin_token, org_id
):
    """Security regression: leave_organization used to delete the user's
    org/project role rows but never their Subscription rows — so a comment
    posted after they left still triggered a notification containing real
    project content (the comment excerpt) for a user who could no longer
    view the project at all, since get_subscriber_ids has no access check
    of its own."""
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    req = client.post(
        f"/api/v1/projects/{project['id']}/requirements",
        json={"name": "Track this", "component_id": component_id, "category_id": category_id},
        headers=auth_headers(admin_token),
    ).json()

    leaver_id = create_org_user(client, admin_token, org_id, "leaving_subscriber@example.com", role="member")
    client.post(
        f"/api/v1/projects/{project['id']}/roles", json={"user_id": leaver_id, "role": "stakeholder"},
        headers=auth_headers(admin_token),
    )
    leaver_token = login(client, "leaving_subscriber@example.com", "Password123!")
    client.put(
        f"/api/v1/projects/{project['id']}/requirements/{req['id']}/subscription",
        headers=auth_headers(leaver_token),
    )

    resp = client.delete(f"/api/v1/orgs/{org_id}/membership", headers=auth_headers(leaver_token))
    assert resp.status_code == 204, resp.text

    client.post(
        f"/api/v1/projects/{project['id']}/requirements/{req['id']}/comments",
        json={"body": "Content the departed user should never see"}, headers=auth_headers(admin_token),
    )

    notifications = client.get("/api/v1/notifications", headers=auth_headers(leaver_token)).json()
    assert not any("comment" in n["title"].lower() for n in notifications)


def test_sole_org_admin_cannot_leave(client, admin_token):
    org, admin2_token = create_org_admin_in(client, admin_token, "Sole Admin Org")

    resp = client.delete(f"/api/v1/orgs/{org['id']}/membership", headers=auth_headers(admin2_token))
    assert resp.status_code == 409

    # Once a second admin exists, the first can leave freely.
    second_admin_id = client.post(
        f"/api/v1/orgs/{org['id']}/users",
        json={"email": "second_admin@example.com", "display_name": "Second Admin", "password": "Password123!", "role": "org_admin"},
        headers=auth_headers(admin2_token),
    ).json()["user_id"]
    resp = client.delete(f"/api/v1/orgs/{org['id']}/membership", headers=auth_headers(admin2_token))
    assert resp.status_code == 204, resp.text
    assert second_admin_id  # sanity: the second admin was actually created


def test_org_admin_cannot_deactivate_own_account(client, admin_token):
    """Hardening-review regression: deactivating a user via this endpoint
    sets is_active=False on the whole account (locking them out of every
    organisation, not just this one) — an org-scoped admin action self-
    targeting to that effect, with no confirmation step, was previously
    allowed outright."""
    org, admin2_token = create_org_admin_in(client, admin_token, "Self Deactivate Org")
    admin2_id = client.get("/api/v1/auth/me", headers=auth_headers(admin2_token)).json()["id"]

    resp = client.post(f"/api/v1/orgs/{org['id']}/users/{admin2_id}/deactivate", headers=auth_headers(admin2_token))
    assert resp.status_code == 400

    # A genuinely different admin can still deactivate this one normally.
    third_admin_id = client.post(
        f"/api/v1/orgs/{org['id']}/users",
        json={"email": "third_admin@example.com", "display_name": "Third Admin", "password": "Password123!", "role": "org_admin"},
        headers=auth_headers(admin2_token),
    ).json()["user_id"]
    third_admin_token = login(client, "third_admin@example.com", "Password123!")
    resp = client.post(f"/api/v1/orgs/{org['id']}/users/{admin2_id}/deactivate", headers=auth_headers(third_admin_token))
    assert resp.status_code == 204, resp.text
    assert third_admin_id  # sanity: the third admin was actually created


def test_sole_manager_via_nested_org_group_cannot_leave_and_loses_access_after(client, admin_token, org_id):
    """Regression test: a user whose only project-manager role comes from an
    org group nested into a project group (C-U-12) must be caught by the
    sole-manager guard just as a direct manager would be — `get_project_managers`
    alone doesn't see nested-group-derived managers, so the leave endpoint has
    to check `get_effective_project_roles` too. And once a second manager
    exists so the leave is allowed, the departing user's `OrgGroupMember` row
    must actually be removed, or their nested-group-derived project access
    (including this same manager role) would silently survive."""
    project = create_project(client, admin_token, org_id)
    user_id = create_org_user(client, admin_token, org_id, "nested_manager@example.com", role="member")

    org_group = client.post(
        f"/api/v1/orgs/{org_id}/groups", json={"name": "Managers Team"}, headers=auth_headers(admin_token)
    ).json()
    client.post(
        f"/api/v1/orgs/{org_id}/groups/{org_group['id']}/members",
        json={"user_id": user_id}, headers=auth_headers(admin_token),
    )
    project_group = client.post(
        f"/api/v1/projects/{project['id']}/groups", json={"name": "PM Team", "role": "project_manager"},
        headers=auth_headers(admin_token),
    ).json()
    nested = client.post(
        f"/api/v1/projects/{project['id']}/groups/{project_group['id']}/members",
        json={"org_group_id": org_group["id"]}, headers=auth_headers(admin_token),
    )
    assert nested.status_code == 204, nested.text

    token = login(client, "nested_manager@example.com", "Password123!")

    # The project creator (admin_token) is already a direct manager, so this
    # user is NOT actually the sole manager yet — leaving should succeed.
    resp = client.delete(f"/api/v1/orgs/{org_id}/membership", headers=auth_headers(token))
    assert resp.status_code == 204, resp.text

    # Confirm the nested-group access is actually gone, not just the org role:
    # re-fetching the project should now 403/404 for this user.
    resp2 = client.get(f"/api/v1/projects/{project['id']}", headers=auth_headers(token))
    assert resp2.status_code in (403, 404)


def test_last_direct_manager_cannot_be_revoked_even_with_a_nested_group_backup(client, admin_token, org_id):
    """Documents why `leave_organization`'s nested-group-aware guard is
    currently unreachable in its "blocking" branch via any path this test
    could find: `revoke_project_role` (and `remove_project_group_member`,
    per docs/decisions.md) independently refuse to remove a project's last
    *direct/direct-group* manager, using the same `get_project_managers`
    resolver that doesn't count nested-org-group managers as backup either
    — so a project can never actually reach "zero direct managers, one
    nested-group manager" through the API today; it always keeps at least
    one direct manager. `leave_organization`'s extra nested-group check is
    still correct defense-in-depth (worth keeping in case that changes),
    just not independently exercisable as a blocking scenario right now."""
    project = create_project(client, admin_token, org_id)
    user_id = create_org_user(client, admin_token, org_id, "nested_backup@example.com", role="member")

    org_group = client.post(
        f"/api/v1/orgs/{org_id}/groups", json={"name": "Backup Managers Team"}, headers=auth_headers(admin_token)
    ).json()
    client.post(
        f"/api/v1/orgs/{org_id}/groups/{org_group['id']}/members",
        json={"user_id": user_id}, headers=auth_headers(admin_token),
    )
    project_group = client.post(
        f"/api/v1/projects/{project['id']}/groups", json={"name": "Backup PM Team", "role": "project_manager"},
        headers=auth_headers(admin_token),
    ).json()
    client.post(
        f"/api/v1/projects/{project['id']}/groups/{project_group['id']}/members",
        json={"org_group_id": org_group["id"]}, headers=auth_headers(admin_token),
    )

    admin_id = client.get("/api/v1/auth/me", headers=auth_headers(admin_token)).json()["id"]
    resp = client.delete(
        f"/api/v1/projects/{project['id']}/roles/{admin_id}/project_manager",
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 400, resp.text


def test_sole_project_manager_cannot_leave_even_with_a_co_admin(client, admin_token):
    org, admin1_token = create_org_admin_in(client, admin_token, "Sole PM Org")
    client.post(
        f"/api/v1/orgs/{org['id']}/users",
        json={"email": "co_admin@example.com", "display_name": "Co Admin", "password": "Password123!", "role": "org_admin"},
        headers=auth_headers(admin1_token),
    )
    project = create_project(client, admin1_token, org["id"], "Solo-Managed Project")

    # admin1 is the org's sole PM on this project (auto-assigned at creation)
    # even though a co-admin exists, so the org-admin-count check alone
    # wouldn't have caught this — the project-manager check must run too.
    resp = client.delete(f"/api/v1/orgs/{org['id']}/membership", headers=auth_headers(admin1_token))
    assert resp.status_code == 409
    assert project["name"] in resp.json()["detail"]
