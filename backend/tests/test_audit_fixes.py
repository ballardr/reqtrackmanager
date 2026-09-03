"""Regression tests for gaps found by the Ossa (v1) / Pelion (v2) requirements
compliance audit (see docs/decisions.md "Requirements audit fixes" section):

- I-M-05: server admins no longer bypass organisation/project data access.
- I-M-06: an existing server admin can grant/revoke the role on another user.
- C-U-02: project roles/groups can't be granted to a user outside the org.
- C-A-05: project-group creation/membership/role changes are audit-logged.
- C-U-08: the last-manager guard also applies to group-based removal.
- C-N-01: a new stage entering scoping notifies project members.
- C-E-04: project creation falls back to the org's default template.
- C-U-16: an org admin can lock/unlock a user's display name via the API.
"""

from tests.conftest import (
    auth_headers,
    create_component_and_category,
    create_org_admin_in,
    create_org_user,
    create_project,
    login,
)


def test_server_admin_cannot_access_org_or_project_data_without_a_role(client, admin_token):
    """I-M-05: the bootstrap server admin has no role in a freshly created
    organisation, so it must not be able to read/write data within it."""
    org = client.post("/api/v1/orgs", json={"name": "No Access Org"}, headers=auth_headers(admin_token)).json()

    assert client.get(f"/api/v1/orgs/{org['id']}/users", headers=auth_headers(admin_token)).status_code == 403
    assert client.post(
        f"/api/v1/orgs/{org['id']}/groups", json={"name": "Team"}, headers=auth_headers(admin_token)
    ).status_code == 403
    assert client.post(
        "/api/v1/projects", json={"organization_id": org["id"], "name": "X", "summary": ""},
        headers=auth_headers(admin_token),
    ).status_code == 403


def test_server_admin_can_still_create_org_and_its_initial_user(client, admin_token):
    """I-M-05's one documented carve-out: creating an org and its initial
    user works with no prior role, even though nothing else does."""
    org = client.post("/api/v1/orgs", json={"name": "Bootstrap Carve-out Org"}, headers=auth_headers(admin_token)).json()
    resp = client.post(
        f"/api/v1/orgs/{org['id']}/users",
        json={"email": "first_admin@example.com", "display_name": "First Admin", "password": "Password123!", "role": "org_admin"},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 201, resp.text


def test_list_organizations_mine_scopes_to_membership_even_for_server_admin(client, admin_token, org_id):
    """The plain `GET /orgs` bypass exists for the platform-level org
    directory (I-M-05's one documented carve-out) — a caller that needs
    "orgs I can actually act within" instead (e.g. the project list's org
    filter/new-project picker) must opt out of it with `mine=true`, or a
    server admin sees every organisation in the deployment there too."""
    other_org = client.post("/api/v1/orgs", json={"name": "Not My Org"}, headers=auth_headers(admin_token)).json()

    all_orgs = client.get("/api/v1/orgs", headers=auth_headers(admin_token)).json()
    assert any(o["id"] == other_org["id"] for o in all_orgs)

    my_orgs = client.get("/api/v1/orgs?mine=true", headers=auth_headers(admin_token)).json()
    my_org_ids = {o["id"] for o in my_orgs}
    assert org_id in my_org_ids
    assert other_org["id"] not in my_org_ids


def test_list_organizations_mine_is_a_noop_for_non_server_admins(client, admin_token, org_id):
    member_email = "mine-param-member@example.com"
    create_org_user(client, admin_token, org_id, member_email, role="member")
    member_token = login(client, member_email, "Password123!")
    default_ids = {o["id"] for o in client.get("/api/v1/orgs", headers=auth_headers(member_token)).json()}
    mine_ids = {o["id"] for o in client.get("/api/v1/orgs?mine=true", headers=auth_headers(member_token)).json()}
    assert default_ids == mine_ids == {org_id}


def test_server_admin_can_make_themselves_org_admin_of_an_org_they_dont_belong_to(client, admin_token):
    """Self-hosting use case: a server admin who is also the only person
    running the deployment needs a way to become admin of their own org,
    not just stand up other people's — `assign_org_role` can't help
    (it requires the caller to already be an org admin of the target org,
    the exact chicken-and-egg this closes)."""
    org = client.post("/api/v1/orgs", json={"name": "Self-Hosted Org"}, headers=auth_headers(admin_token)).json()

    # Blocked beforehand, same as any other org-scoped action (I-M-05).
    assert client.get(f"/api/v1/orgs/{org['id']}/groups", headers=auth_headers(admin_token)).status_code == 403

    resp = client.post(f"/api/v1/orgs/{org['id']}/join-as-admin", headers=auth_headers(admin_token))
    assert resp.status_code == 204

    # Now a genuine member — every ordinary org-admin action works.
    assert client.get(f"/api/v1/orgs/{org['id']}/groups", headers=auth_headers(admin_token)).status_code == 200
    assert client.post(
        f"/api/v1/orgs/{org['id']}/groups", json={"name": "Team"}, headers=auth_headers(admin_token)
    ).status_code == 201


def test_cannot_join_as_admin_twice(client, admin_token):
    org = client.post("/api/v1/orgs", json={"name": "Double Join Org"}, headers=auth_headers(admin_token)).json()
    assert client.post(f"/api/v1/orgs/{org['id']}/join-as-admin", headers=auth_headers(admin_token)).status_code == 204
    resp = client.post(f"/api/v1/orgs/{org['id']}/join-as-admin", headers=auth_headers(admin_token))
    assert resp.status_code == 400


def test_non_server_admin_cannot_join_as_admin(client, admin_token, org_id):
    """A plain org member/admin elsewhere on the deployment must not be
    able to grant themselves admin of an unrelated organisation."""
    other_org = client.post("/api/v1/orgs", json={"name": "Unrelated Org"}, headers=auth_headers(admin_token)).json()
    create_org_user(client, admin_token, org_id, "plain_joiner@example.com", role="member")
    token = login(client, "plain_joiner@example.com", "Password123!")
    resp = client.post(f"/api/v1/orgs/{other_org['id']}/join-as-admin", headers=auth_headers(token))
    assert resp.status_code == 403


def test_grant_and_revoke_server_admin_role(client, admin_token, org_id):
    """I-M-06: an existing server admin can promote/demote another user."""
    user_id = create_org_user(client, admin_token, org_id, "future_admin@example.com", role="member")

    granted = client.put(
        f"/api/v1/system/users/{user_id}/server-admin", json={"is_server_admin": True},
        headers=auth_headers(admin_token),
    )
    assert granted.status_code == 204, granted.text

    new_admin_token = login(client, "future_admin@example.com", "Password123!")
    # Prove the grant actually took effect: they can now do a server-admin-only action.
    created_org = client.post(
        "/api/v1/orgs", json={"name": "Created By New Admin"}, headers=auth_headers(new_admin_token)
    )
    assert created_org.status_code == 201, created_org.text

    revoked = client.put(
        f"/api/v1/system/users/{user_id}/server-admin", json={"is_server_admin": False},
        headers=auth_headers(admin_token),
    )
    assert revoked.status_code == 204
    demoted_token = login(client, "future_admin@example.com", "Password123!")
    assert client.post(
        "/api/v1/orgs", json={"name": "Should Fail Now"}, headers=auth_headers(demoted_token)
    ).status_code == 403


def test_non_server_admin_cannot_grant_server_admin_role(client, admin_token, org_id):
    member_id = create_org_user(client, admin_token, org_id, "plain_member@example.com", role="member")
    token = login(client, "plain_member@example.com", "Password123!")
    resp = client.put(
        f"/api/v1/system/users/{member_id}/server-admin", json={"is_server_admin": True}, headers=auth_headers(token)
    )
    assert resp.status_code == 403


def test_cannot_grant_project_role_to_user_outside_the_organisation(client, admin_token, org_id):
    """C-U-02: "All Project users, must be an organisation user." """
    project = create_project(client, admin_token, org_id)
    other_org, other_org_admin_token = create_org_admin_in(client, admin_token, "Outsider Org")
    outsider_id = create_org_user(client, other_org_admin_token, other_org["id"], "outsider@example.com", role="member")

    resp = client.post(
        f"/api/v1/projects/{project['id']}/roles",
        json={"user_id": outsider_id, "role": "member"},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 400


def test_project_group_changes_are_audit_logged(client, admin_token, org_id):
    """C-A-05: project-group creation and membership changes appear in the
    project changes-over-time view, matching org-group changes."""
    project = create_project(client, admin_token, org_id)
    member_id = create_org_user(client, admin_token, org_id, "group_member@example.com", role="member")

    group = client.post(
        f"/api/v1/projects/{project['id']}/groups", json={"name": "Reviewers"},
        headers=auth_headers(admin_token),
    ).json()
    client.post(
        f"/api/v1/projects/{project['id']}/groups/{group['id']}/members",
        json={"user_id": member_id}, headers=auth_headers(admin_token),
    )
    client.delete(
        f"/api/v1/projects/{project['id']}/groups/{group['id']}/members/{member_id}",
        headers=auth_headers(admin_token),
    )

    changes = client.get(f"/api/v1/projects/{project['id']}/changes", headers=auth_headers(admin_token)).json()
    actions = {c["action"] for c in changes if c["entity_type"] == "project_group"}
    assert {"created", "member_added", "member_removed"} <= actions


def test_last_manager_guard_applies_to_group_based_removal(client, admin_token, org_id):
    """C-U-08: removing a project's only manager via group membership must
    be blocked, the same as direct role revocation already is.

    A fresh project's creator now holds their initial manager role via a
    direct grant, not group membership (C-U-10, follow-up UX batch Phase C,
    2026-08-31 removed the auto-created default groups) — so this test
    first builds a manager-role group with a *different* user as its sole
    member, then revokes the creator's own direct grant, leaving that group
    membership as the project's only remaining manager source, the
    scenario this guard actually needs to cover."""
    project = create_project(client, admin_token, org_id)
    me = client.get("/api/v1/auth/me", headers=auth_headers(admin_token)).json()
    other_id = create_org_user(client, admin_token, org_id, "group-based-sole-manager@example.com", role="member")
    group = client.post(
        f"/api/v1/projects/{project['id']}/groups", json={"name": "Managers"},
        headers=auth_headers(admin_token),
    ).json()
    grant_role = client.post(
        f"/api/v1/projects/{project['id']}/groups/{group['id']}/roles", json={"role": "project_manager"},
        headers=auth_headers(admin_token),
    )
    assert grant_role.status_code == 204, grant_role.text
    added = client.post(
        f"/api/v1/projects/{project['id']}/groups/{group['id']}/members",
        json={"user_id": other_id}, headers=auth_headers(admin_token),
    )
    assert added.status_code == 204, added.text
    revoke = client.delete(
        f"/api/v1/projects/{project['id']}/roles/{me['id']}/project_manager", headers=auth_headers(admin_token)
    )
    assert revoke.status_code == 204, revoke.text

    resp = client.delete(
        f"/api/v1/projects/{project['id']}/groups/{group['id']}/members/{other_id}",
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 400


def test_new_stage_entering_scoping_notifies_members(client, admin_token, org_id):
    """C-N-01: a newly created (non-initial) stage entering scoping notifies
    project members — this is never the "brand new project" excluded case.

    Uses a second member distinct from the creator: `admin_token` is both
    the one creating the stage and (per `create_project`) already a project
    manager, so checking their own notifications wouldn't distinguish "the
    broadcast works" from "self-notifications aren't suppressed" — the
    self-notification-suppression fix (see docs/decisions.md) makes those
    two outcomes different."""
    project = create_project(client, admin_token, org_id)
    member_id = create_org_user(client, admin_token, org_id, "stage-scoping-member@example.com", role="member")
    client.post(
        f"/api/v1/projects/{project['id']}/roles", json={"user_id": member_id, "role": "stakeholder"},
        headers=auth_headers(admin_token),
    )
    member_token = login(client, "stage-scoping-member@example.com", "Password123!")

    client.post(
        f"/api/v1/projects/{project['id']}/stages", json={"name": "Build"}, headers=auth_headers(admin_token)
    )
    notifications = client.get("/api/v1/notifications", headers=auth_headers(member_token)).json()
    assert any(n["type"] == "stage_scoping" for n in notifications)
    own_notifications = client.get("/api/v1/notifications", headers=auth_headers(admin_token)).json()
    assert not any(n["type"] == "stage_scoping" for n in own_notifications)


def test_project_creation_falls_back_to_org_default_template(client, admin_token, org_id):
    """C-E-04: omitting template_project_id uses the org's configured default."""
    template = create_project(client, admin_token, org_id, "Default Template Source")
    client.patch(f"/api/v1/projects/{template['id']}", json={"is_template": True}, headers=auth_headers(admin_token))
    client.put(
        f"/api/v1/orgs/{org_id}/default-template", json={"project_id": template["id"]}, headers=auth_headers(admin_token)
    )
    component_id, category_id = create_component_and_category(client, admin_token, template["id"])

    created = client.post(
        "/api/v1/projects", json={"organization_id": org_id, "name": "No Template Specified", "summary": ""},
        headers=auth_headers(admin_token),
    )
    assert created.status_code == 201, created.text
    new_project = created.json()

    components = client.get(
        f"/api/v1/projects/{new_project['id']}/components", headers=auth_headers(admin_token)
    ).json()
    assert any(c["id"] == component_id or c["prefix"] == "SW" for c in components)


def test_org_admin_can_lock_and_unlock_display_name(client, admin_token, org_id):
    """C-U-16: an org admin can lock/unlock a user's display name, and the
    user is rejected when they try to change it while locked."""
    user_id = create_org_user(client, admin_token, org_id, "lockable@example.com", role="member")
    token = login(client, "lockable@example.com", "Password123!")

    locked = client.put(
        f"/api/v1/orgs/{org_id}/users/{user_id}/display-name-lock",
        json={"display_name_locked": True}, headers=auth_headers(admin_token),
    )
    assert locked.status_code == 204

    rejected = client.patch(
        "/api/v1/auth/me/preferences", json={"display_name": "New Name"}, headers=auth_headers(token)
    )
    assert rejected.status_code == 403

    users = client.get(f"/api/v1/orgs/{org_id}/users", headers=auth_headers(admin_token)).json()
    assert next(u for u in users if u["user_id"] == user_id)["display_name_locked"] is True

    unlocked = client.put(
        f"/api/v1/orgs/{org_id}/users/{user_id}/display-name-lock",
        json={"display_name_locked": False}, headers=auth_headers(admin_token),
    )
    assert unlocked.status_code == 204
    allowed = client.patch(
        "/api/v1/auth/me/preferences", json={"display_name": "New Name"}, headers=auth_headers(token)
    )
    assert allowed.status_code == 200
