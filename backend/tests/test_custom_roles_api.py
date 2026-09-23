"""Tests for Fine-Grained Access Control's Phase 3 backend API
(`docs/plans/core-fine-grained-access-control-plan.md`): the `GET .../
permissions` vocabulary endpoint, `CustomRoleDefinition` CRUD (`ORG_ADMIN`-
only, never delegable — Phase 0 Q5), its user/group grant/revoke endpoints
(delegable via `grant_roles` — Phase 0 Q6), tenant isolation, the
`scope`/`project_id` cross-validation, and the `grant_roles` wiring onto
the six pre-existing role-assignment endpoints (including the `OrgRole.
ORG_ADMIN` carve-out).

Phases 1/2's own test files (`test_custom_roles.py`, `test_effective_
permissions.py`) cover the data model and resolution engine directly; this
file is the first to exercise the actual HTTP surface built on top of them.
"""

from __future__ import annotations

import uuid as uuid_lib

from app.database import SessionLocal
from app.models.custom_role import CustomRoleDefinition, CustomRolePermission, GroupCustomRoleGrant, UserCustomRoleGrant
from tests.conftest import auth_headers, create_org_admin_in, create_org_user, create_project, login

# --- Helpers ------------------------------------------------------------


def _grant_roles_only_user(client, admin_token, org, name="grant_roles_holder") -> tuple[str, str]:
    """Creates a plain org member, then grants them a `CustomRoleDefinition`
    holding only `grant_roles` — a `grant_roles`-only holder with no
    `ORG_ADMIN`/`PROJECT_MANAGER` role of their own, the fixture every
    delegability assertion in this file needs. Returns (user_id, token)."""
    email = f"{name}_{uuid_lib.uuid4().hex[:8]}@example.com"
    user_id = create_org_user(client, admin_token, org["id"], email, role="member")
    resp = client.post(
        f"/api/v1/orgs/{org['id']}/custom-roles",
        json={"name": f"Grant Roles Holder {uuid_lib.uuid4().hex[:8]}", "description": "", "scope": "org", "permissions": ["grant_roles"]},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 201, resp.text
    role = resp.json()
    grant_resp = client.post(
        f"/api/v1/orgs/{org['id']}/custom-roles/{role['id']}/users/{user_id}",
        json={}, headers=auth_headers(admin_token),
    )
    assert grant_resp.status_code == 204, grant_resp.text
    token = login(client, email, "Password123!")
    return user_id, token


# --- GET /permissions -----------------------------------------------------


def test_list_permissions_shape_for_fresh_org(client, admin_token):
    org, org_admin_token = create_org_admin_in(client, admin_token, "Permissions Vocabulary Org")
    resp = client.get(f"/api/v1/orgs/{org['id']}/permissions", headers=auth_headers(org_admin_token))
    assert resp.status_code == 200, resp.text
    permissions = resp.json()
    keys = {p["key"] for p in permissions}
    assert "grant_roles" in keys
    assert "manage_members" in keys
    grant_roles_entry = next(p for p in permissions if p["key"] == "grant_roles")
    assert grant_roles_entry["artefact_type"] is None
    assert grant_roles_entry["level"] is None
    assert grant_roles_entry["subtype"] is None
    requirement_view_key = next((p["key"] for p in permissions if p["artefact_type"] == "requirement" and p["level"] == "view"), None)
    assert requirement_view_key is not None


def test_list_permissions_open_to_any_org_member(client, admin_token):
    org, org_admin_token = create_org_admin_in(client, admin_token, "Permissions Open Org")
    _member_id = create_org_user(client, org_admin_token, org["id"], "perm_plain_member@example.com", role="member")
    member_token = login(client, "perm_plain_member@example.com", "Password123!")
    resp = client.get(f"/api/v1/orgs/{org['id']}/permissions", headers=auth_headers(member_token))
    assert resp.status_code == 200, resp.text


# --- CustomRoleDefinition CRUD (ORG_ADMIN-only, non-delegable) -------------


def test_create_custom_role_and_get_and_list(client, admin_token):
    org, org_admin_token = create_org_admin_in(client, admin_token, "Custom Role CRUD Org")
    resp = client.post(
        f"/api/v1/orgs/{org['id']}/custom-roles",
        json={"name": "Reviewer", "description": "Reviews things", "scope": "org", "permissions": ["grant_roles"]},
        headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 201, resp.text
    role = resp.json()
    assert role["name"] == "Reviewer"
    assert role["scope"] == "org"
    assert role["permissions"] == ["grant_roles"]
    assert role["organization_id"] == org["id"]

    get_resp = client.get(f"/api/v1/orgs/{org['id']}/custom-roles/{role['id']}", headers=auth_headers(org_admin_token))
    assert get_resp.status_code == 200, get_resp.text
    assert get_resp.json()["id"] == role["id"]

    list_resp = client.get(f"/api/v1/orgs/{org['id']}/custom-roles", headers=auth_headers(org_admin_token))
    assert list_resp.status_code == 200, list_resp.text
    assert any(r["id"] == role["id"] for r in list_resp.json())


def test_create_custom_role_rejects_invalid_permission_key(client, admin_token):
    org, org_admin_token = create_org_admin_in(client, admin_token, "Invalid Permission Org")
    resp = client.post(
        f"/api/v1/orgs/{org['id']}/custom-roles",
        json={"name": "Bad Role", "description": "", "scope": "org", "permissions": ["not_a_real_permission"]},
        headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 400, resp.text


def test_create_custom_role_rejects_invalid_scope(client, admin_token):
    org, org_admin_token = create_org_admin_in(client, admin_token, "Invalid Scope Org")
    resp = client.post(
        f"/api/v1/orgs/{org['id']}/custom-roles",
        json={"name": "Bad Scope Role", "description": "", "scope": "standard", "permissions": []},
        headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 400, resp.text


def test_create_custom_role_rejects_duplicate_name_cleanly(client, admin_token):
    org, org_admin_token = create_org_admin_in(client, admin_token, "Duplicate Name Org")
    payload = {"name": "Duplicate", "description": "", "scope": "org", "permissions": []}
    first = client.post(f"/api/v1/orgs/{org['id']}/custom-roles", json=payload, headers=auth_headers(org_admin_token))
    assert first.status_code == 201, first.text
    second = client.post(f"/api/v1/orgs/{org['id']}/custom-roles", json=payload, headers=auth_headers(org_admin_token))
    assert second.status_code == 409, second.text


def test_custom_role_crud_rejects_non_admin_org_member(client, admin_token):
    org, org_admin_token = create_org_admin_in(client, admin_token, "Non Admin CRUD Org")
    _member_id = create_org_user(client, org_admin_token, org["id"], "crud_plain_member@example.com", role="member")
    member_token = login(client, "crud_plain_member@example.com", "Password123!")

    create_resp = client.post(
        f"/api/v1/orgs/{org['id']}/custom-roles",
        json={"name": "Should Fail", "description": "", "scope": "org", "permissions": []},
        headers=auth_headers(member_token),
    )
    assert create_resp.status_code == 403


def test_custom_role_crud_rejects_grant_roles_only_holder(client, admin_token):
    """Confirms Phase 0 Q5: role *definition* (create/update/delete) is
    never delegable via `grant_roles`, unlike *assignment* below."""
    org, org_admin_token = create_org_admin_in(client, admin_token, "Grant Roles Non Delegable Org")
    _user_id, grant_roles_token = _grant_roles_only_user(client, org_admin_token, org)

    create_resp = client.post(
        f"/api/v1/orgs/{org['id']}/custom-roles",
        json={"name": "Should Also Fail", "description": "", "scope": "org", "permissions": []},
        headers=auth_headers(grant_roles_token),
    )
    assert create_resp.status_code == 403

    # Also reject update/delete of an existing role.
    existing = client.post(
        f"/api/v1/orgs/{org['id']}/custom-roles",
        json={"name": "Existing Role", "description": "", "scope": "org", "permissions": []},
        headers=auth_headers(org_admin_token),
    )
    assert existing.status_code == 201, existing.text
    role_id = existing.json()["id"]

    update_resp = client.patch(
        f"/api/v1/orgs/{org['id']}/custom-roles/{role_id}",
        json={"description": "Hacked"},
        headers=auth_headers(grant_roles_token),
    )
    assert update_resp.status_code == 403

    delete_resp = client.delete(
        f"/api/v1/orgs/{org['id']}/custom-roles/{role_id}", headers=auth_headers(grant_roles_token)
    )
    assert delete_resp.status_code == 403


def test_update_custom_role_partial_update(client, admin_token):
    org, org_admin_token = create_org_admin_in(client, admin_token, "Custom Role Update Org")
    created = client.post(
        f"/api/v1/orgs/{org['id']}/custom-roles",
        json={"name": "Original Name", "description": "Original", "scope": "org", "permissions": ["grant_roles"]},
        headers=auth_headers(org_admin_token),
    )
    role_id = created.json()["id"]

    resp = client.patch(
        f"/api/v1/orgs/{org['id']}/custom-roles/{role_id}",
        json={"description": "Updated description only"},
        headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 200, resp.text
    updated = resp.json()
    assert updated["name"] == "Original Name"
    assert updated["description"] == "Updated description only"
    assert updated["permissions"] == ["grant_roles"]


def test_update_custom_role_replaces_permission_set(client, admin_token):
    org, org_admin_token = create_org_admin_in(client, admin_token, "Custom Role Permission Replace Org")
    created = client.post(
        f"/api/v1/orgs/{org['id']}/custom-roles",
        json={"name": "Permission Replace Role", "description": "", "scope": "org", "permissions": ["grant_roles", "manage_members"]},
        headers=auth_headers(org_admin_token),
    )
    role_id = created.json()["id"]

    resp = client.patch(
        f"/api/v1/orgs/{org['id']}/custom-roles/{role_id}",
        json={"permissions": ["manage_settings"]},
        headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["permissions"] == ["manage_settings"]


def test_delete_custom_role_cascades_grants(client, admin_token):
    org, org_admin_token = create_org_admin_in(client, admin_token, "Custom Role Delete Cascade Org")
    grantee_id = create_org_user(client, org_admin_token, org["id"], "cascade_grantee@example.com", role="member")
    created = client.post(
        f"/api/v1/orgs/{org['id']}/custom-roles",
        json={"name": "To Delete", "description": "", "scope": "org", "permissions": []},
        headers=auth_headers(org_admin_token),
    )
    role_id = created.json()["id"]
    grant_resp = client.post(
        f"/api/v1/orgs/{org['id']}/custom-roles/{role_id}/users/{grantee_id}",
        json={}, headers=auth_headers(org_admin_token),
    )
    assert grant_resp.status_code == 204, grant_resp.text

    delete_resp = client.delete(f"/api/v1/orgs/{org['id']}/custom-roles/{role_id}", headers=auth_headers(org_admin_token))
    assert delete_resp.status_code == 204, delete_resp.text

    db = SessionLocal()
    try:
        assert db.get(CustomRoleDefinition, uuid_lib.UUID(role_id)) is None
        assert db.query(CustomRolePermission).filter(CustomRolePermission.custom_role_id == uuid_lib.UUID(role_id)).count() == 0
        assert db.query(UserCustomRoleGrant).filter(UserCustomRoleGrant.custom_role_id == uuid_lib.UUID(role_id)).count() == 0
    finally:
        db.close()

    get_resp = client.get(f"/api/v1/orgs/{org['id']}/custom-roles/{role_id}", headers=auth_headers(org_admin_token))
    assert get_resp.status_code == 404


# --- Tenant isolation -------------------------------------------------------


def test_custom_role_from_org_a_is_404_via_org_b(client, admin_token):
    org_a, org_a_admin_token = create_org_admin_in(client, admin_token, "Isolation Org A")
    org_b, org_b_admin_token = create_org_admin_in(client, admin_token, "Isolation Org B")
    grantee_id = create_org_user(client, org_b_admin_token, org_b["id"], "isolation_grantee@example.com", role="member")

    created = client.post(
        f"/api/v1/orgs/{org_a['id']}/custom-roles",
        json={"name": "A Only", "description": "", "scope": "org", "permissions": []},
        headers=auth_headers(org_a_admin_token),
    )
    role_id = created.json()["id"]

    get_resp = client.get(f"/api/v1/orgs/{org_b['id']}/custom-roles/{role_id}", headers=auth_headers(org_b_admin_token))
    assert get_resp.status_code == 404

    grant_resp = client.post(
        f"/api/v1/orgs/{org_b['id']}/custom-roles/{role_id}/users/{grantee_id}",
        json={}, headers=auth_headers(org_b_admin_token),
    )
    assert grant_resp.status_code == 404


# --- scope / project_id cross-validation ------------------------------------


def test_org_scoped_role_rejects_project_id_on_grant(client, admin_token):
    org, org_admin_token = create_org_admin_in(client, admin_token, "Org Scope Reject Project Org")
    project = create_project(client, org_admin_token, org["id"])
    grantee_id = create_org_user(client, org_admin_token, org["id"], "org_scope_grantee@example.com", role="member")
    created = client.post(
        f"/api/v1/orgs/{org['id']}/custom-roles",
        json={"name": "Org Scoped", "description": "", "scope": "org", "permissions": []},
        headers=auth_headers(org_admin_token),
    )
    role_id = created.json()["id"]

    resp = client.post(
        f"/api/v1/orgs/{org['id']}/custom-roles/{role_id}/users/{grantee_id}",
        json={"project_id": project["id"]}, headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 400


def test_project_scoped_role_requires_project_id_on_grant(client, admin_token):
    org, org_admin_token = create_org_admin_in(client, admin_token, "Project Scope Require Org")
    grantee_id = create_org_user(client, org_admin_token, org["id"], "project_scope_grantee@example.com", role="member")
    created = client.post(
        f"/api/v1/orgs/{org['id']}/custom-roles",
        json={"name": "Project Scoped", "description": "", "scope": "project", "permissions": []},
        headers=auth_headers(org_admin_token),
    )
    role_id = created.json()["id"]

    resp = client.post(
        f"/api/v1/orgs/{org['id']}/custom-roles/{role_id}/users/{grantee_id}",
        json={}, headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 400


# --- Grant/revoke: user + group, ORG_ADMIN and grant_roles-only holder -----


def test_grant_and_revoke_custom_role_to_user_via_org_admin(client, admin_token):
    org, org_admin_token = create_org_admin_in(client, admin_token, "User Grant Org Admin Org")
    grantee_id = create_org_user(client, org_admin_token, org["id"], "user_grant_grantee@example.com", role="member")
    created = client.post(
        f"/api/v1/orgs/{org['id']}/custom-roles",
        json={"name": "Grantable Role", "description": "", "scope": "org", "permissions": ["grant_roles"]},
        headers=auth_headers(org_admin_token),
    )
    role_id = created.json()["id"]

    grant_resp = client.post(
        f"/api/v1/orgs/{org['id']}/custom-roles/{role_id}/users/{grantee_id}",
        json={}, headers=auth_headers(org_admin_token),
    )
    assert grant_resp.status_code == 204, grant_resp.text

    revoke_resp = client.delete(
        f"/api/v1/orgs/{org['id']}/custom-roles/{role_id}/users/{grantee_id}", headers=auth_headers(org_admin_token)
    )
    assert revoke_resp.status_code == 204, revoke_resp.text

    db = SessionLocal()
    try:
        assert db.query(UserCustomRoleGrant).filter(
            UserCustomRoleGrant.custom_role_id == uuid_lib.UUID(role_id),
            UserCustomRoleGrant.user_id == uuid_lib.UUID(grantee_id),
        ).count() == 0
    finally:
        db.close()


def test_org_user_listing_surfaces_org_scoped_custom_role_grants(client, admin_token):
    """`GET /orgs/{id}/users` surfaces each user's own org-scoped
    (`project_id` null) custom-role grants via `OrgUserOut.custom_roles`
    (frontend Role Management UI, Phase 3) — the same "attach this user's
    own grants" treatment `ModuleRoleGrantOut`/`module_roles` already gets,
    extended to custom roles. Pins the shape (`custom_role_id`/`name`) and
    that a revoke removes the entry again, mirroring `test_org_module_role_
    grant_and_revoke_idempotent`'s equivalent assertion for module roles."""
    org, org_admin_token = create_org_admin_in(client, admin_token, "User Listing Custom Role Org")
    grantee_id = create_org_user(client, org_admin_token, org["id"], "listing_grantee@example.com", role="member")
    created = client.post(
        f"/api/v1/orgs/{org['id']}/custom-roles",
        json={"name": "Listed Role", "description": "", "scope": "org", "permissions": []},
        headers=auth_headers(org_admin_token),
    )
    role_id = created.json()["id"]

    resp = client.get(f"/api/v1/orgs/{org['id']}/users", headers=auth_headers(org_admin_token))
    by_id = {u["user_id"]: u for u in resp.json()}
    assert by_id[grantee_id]["custom_roles"] == []

    grant_resp = client.post(
        f"/api/v1/orgs/{org['id']}/custom-roles/{role_id}/users/{grantee_id}",
        json={}, headers=auth_headers(org_admin_token),
    )
    assert grant_resp.status_code == 204, grant_resp.text

    resp = client.get(f"/api/v1/orgs/{org['id']}/users", headers=auth_headers(org_admin_token))
    by_id = {u["user_id"]: u for u in resp.json()}
    assert by_id[grantee_id]["custom_roles"] == [{"custom_role_id": role_id, "name": "Listed Role"}]

    revoke_resp = client.delete(
        f"/api/v1/orgs/{org['id']}/custom-roles/{role_id}/users/{grantee_id}", headers=auth_headers(org_admin_token)
    )
    assert revoke_resp.status_code == 204, revoke_resp.text

    resp = client.get(f"/api/v1/orgs/{org['id']}/users", headers=auth_headers(org_admin_token))
    by_id = {u["user_id"]: u for u in resp.json()}
    assert by_id[grantee_id]["custom_roles"] == []


def test_project_scoped_custom_role_grant_not_surfaced_on_user_listing(client, admin_token):
    """A project-scoped `CustomRoleDefinition`'s grant is deliberately
    excluded from `OrgUserOut.custom_roles` (`CustomRoleGrantOut`'s own
    docstring) — there is no single project column on the org-wide Users
    table for it to attach to, mirroring `module_roles`' identical
    org-scope-only limit."""
    org, org_admin_token = create_org_admin_in(client, admin_token, "Project Scoped Not Listed Org")
    project = create_project(client, org_admin_token, org["id"], "Project Scoped Role Project")
    grantee_id = create_org_user(client, org_admin_token, org["id"], "project_scoped_grantee@example.com", role="member")
    created = client.post(
        f"/api/v1/orgs/{org['id']}/custom-roles",
        json={"name": "Project Scoped Role", "description": "", "scope": "project", "permissions": []},
        headers=auth_headers(org_admin_token),
    )
    role_id = created.json()["id"]

    grant_resp = client.post(
        f"/api/v1/orgs/{org['id']}/custom-roles/{role_id}/users/{grantee_id}",
        json={"project_id": project["id"]}, headers=auth_headers(org_admin_token),
    )
    assert grant_resp.status_code == 204, grant_resp.text

    resp = client.get(f"/api/v1/orgs/{org['id']}/users", headers=auth_headers(org_admin_token))
    by_id = {u["user_id"]: u for u in resp.json()}
    assert by_id[grantee_id]["custom_roles"] == []


def test_grant_and_revoke_custom_role_to_user_via_grant_roles_only_holder(client, admin_token):
    """Confirms Phase 0 Q6: role *assignment* is delegable via `grant_roles`."""
    org, org_admin_token = create_org_admin_in(client, admin_token, "User Grant Delegable Org")
    grantee_id = create_org_user(client, org_admin_token, org["id"], "delegable_grantee@example.com", role="member")
    _holder_id, grant_roles_token = _grant_roles_only_user(client, org_admin_token, org)

    created = client.post(
        f"/api/v1/orgs/{org['id']}/custom-roles",
        json={"name": "Delegable Grant Role", "description": "", "scope": "org", "permissions": []},
        headers=auth_headers(org_admin_token),
    )
    role_id = created.json()["id"]

    grant_resp = client.post(
        f"/api/v1/orgs/{org['id']}/custom-roles/{role_id}/users/{grantee_id}",
        json={}, headers=auth_headers(grant_roles_token),
    )
    assert grant_resp.status_code == 204, grant_resp.text

    revoke_resp = client.delete(
        f"/api/v1/orgs/{org['id']}/custom-roles/{role_id}/users/{grantee_id}", headers=auth_headers(grant_roles_token)
    )
    assert revoke_resp.status_code == 204, revoke_resp.text


def test_grant_custom_role_no_op_on_duplicate(client, admin_token):
    org, org_admin_token = create_org_admin_in(client, admin_token, "Duplicate Grant Org")
    grantee_id = create_org_user(client, org_admin_token, org["id"], "duplicate_grant_grantee@example.com", role="member")
    created = client.post(
        f"/api/v1/orgs/{org['id']}/custom-roles",
        json={"name": "Duplicate Grant Role", "description": "", "scope": "org", "permissions": []},
        headers=auth_headers(org_admin_token),
    )
    role_id = created.json()["id"]

    first = client.post(
        f"/api/v1/orgs/{org['id']}/custom-roles/{role_id}/users/{grantee_id}",
        json={}, headers=auth_headers(org_admin_token),
    )
    assert first.status_code == 204
    second = client.post(
        f"/api/v1/orgs/{org['id']}/custom-roles/{role_id}/users/{grantee_id}",
        json={}, headers=auth_headers(org_admin_token),
    )
    assert second.status_code == 204

    db = SessionLocal()
    try:
        assert db.query(UserCustomRoleGrant).filter(
            UserCustomRoleGrant.custom_role_id == uuid_lib.UUID(role_id),
            UserCustomRoleGrant.user_id == uuid_lib.UUID(grantee_id),
        ).count() == 1
    finally:
        db.close()


def test_grant_and_revoke_custom_role_to_group(client, admin_token):
    org, org_admin_token = create_org_admin_in(client, admin_token, "Group Grant Org")
    group_resp = client.post(
        f"/api/v1/orgs/{org['id']}/groups", json={"name": "Reviewers Group"}, headers=auth_headers(org_admin_token)
    )
    assert group_resp.status_code == 201, group_resp.text
    group_id = group_resp.json()["id"]

    created = client.post(
        f"/api/v1/orgs/{org['id']}/custom-roles",
        json={"name": "Group Grantable Role", "description": "", "scope": "org", "permissions": []},
        headers=auth_headers(org_admin_token),
    )
    role_id = created.json()["id"]

    grant_resp = client.post(
        f"/api/v1/orgs/{org['id']}/custom-roles/{role_id}/groups/{group_id}",
        json={}, headers=auth_headers(org_admin_token),
    )
    assert grant_resp.status_code == 204, grant_resp.text

    revoke_resp = client.delete(
        f"/api/v1/orgs/{org['id']}/custom-roles/{role_id}/groups/{group_id}", headers=auth_headers(org_admin_token)
    )
    assert revoke_resp.status_code == 204, revoke_resp.text

    db = SessionLocal()
    try:
        assert db.query(GroupCustomRoleGrant).filter(
            GroupCustomRoleGrant.custom_role_id == uuid_lib.UUID(role_id),
            GroupCustomRoleGrant.org_group_id == uuid_lib.UUID(group_id),
        ).count() == 0
    finally:
        db.close()


def test_grant_custom_role_to_group_via_grant_roles_only_holder(client, admin_token):
    org, org_admin_token = create_org_admin_in(client, admin_token, "Group Grant Delegable Org")
    group_resp = client.post(
        f"/api/v1/orgs/{org['id']}/groups", json={"name": "Delegable Group"}, headers=auth_headers(org_admin_token)
    )
    group_id = group_resp.json()["id"]
    _holder_id, grant_roles_token = _grant_roles_only_user(client, org_admin_token, org)

    created = client.post(
        f"/api/v1/orgs/{org['id']}/custom-roles",
        json={"name": "Group Delegable Role", "description": "", "scope": "org", "permissions": []},
        headers=auth_headers(org_admin_token),
    )
    role_id = created.json()["id"]

    grant_resp = client.post(
        f"/api/v1/orgs/{org['id']}/custom-roles/{role_id}/groups/{group_id}",
        json={}, headers=auth_headers(grant_roles_token),
    )
    assert grant_resp.status_code == 204, grant_resp.text


# --- grant_roles wiring onto the six pre-existing endpoints -----------------


def test_assign_org_role_reachable_via_grant_roles_holder_but_not_org_admin_value(client, admin_token):
    org, org_admin_token = create_org_admin_in(client, admin_token, "Org Role Wiring Org")
    target_id = create_org_user(client, org_admin_token, org["id"], "org_role_wiring_target@example.com", role="member")
    _holder_id, grant_roles_token = _grant_roles_only_user(client, org_admin_token, org)

    # A grant_roles-only holder CAN grant a non-ORG_ADMIN fixed role.
    ok_resp = client.post(
        f"/api/v1/orgs/{org['id']}/users/{target_id}/roles",
        json={"user_id": target_id, "role": "project_creator"},
        headers=auth_headers(grant_roles_token),
    )
    assert ok_resp.status_code == 204, ok_resp.text

    # ...but is rejected specifically for OrgRole.ORG_ADMIN itself (Phase 0 Q6 carve-out).
    admin_resp = client.post(
        f"/api/v1/orgs/{org['id']}/users/{target_id}/roles",
        json={"user_id": target_id, "role": "org_admin"},
        headers=auth_headers(grant_roles_token),
    )
    assert admin_resp.status_code == 403, admin_resp.text

    # Revoke: same carve-out.
    revoke_admin_resp = client.delete(
        f"/api/v1/orgs/{org['id']}/users/{target_id}/roles/org_admin", headers=auth_headers(grant_roles_token)
    )
    assert revoke_admin_resp.status_code == 403

    revoke_ok_resp = client.delete(
        f"/api/v1/orgs/{org['id']}/users/{target_id}/roles/project_creator", headers=auth_headers(grant_roles_token)
    )
    assert revoke_ok_resp.status_code == 204, revoke_ok_resp.text


def test_assign_org_role_still_rejects_caller_with_neither_grant_roles_nor_org_admin(client, admin_token):
    org, org_admin_token = create_org_admin_in(client, admin_token, "Org Role No Widening Org")
    target_id = create_org_user(client, org_admin_token, org["id"], "no_widening_target@example.com", role="member")
    _plain_id = create_org_user(client, org_admin_token, org["id"], "no_widening_plain@example.com", role="member")
    plain_token = login(client, "no_widening_plain@example.com", "Password123!")

    resp = client.post(
        f"/api/v1/orgs/{org['id']}/users/{target_id}/roles",
        json={"user_id": target_id, "role": "project_creator"},
        headers=auth_headers(plain_token),
    )
    assert resp.status_code == 403


def test_assign_org_module_role_gate_widened(client, admin_token):
    org, org_admin_token = create_org_admin_in(client, admin_token, "Org Module Role Wiring Org")
    target_id = create_org_user(client, org_admin_token, org["id"], "org_module_role_target@example.com", role="member")
    _plain_id = create_org_user(client, org_admin_token, org["id"], "org_module_role_plain@example.com", role="member")
    plain_token = login(client, "org_module_role_plain@example.com", "Password123!")
    _holder_id, grant_roles_token = _grant_roles_only_user(client, org_admin_token, org)

    # No real module role exists in tests generically, so exercise the gate
    # via the 400 "not a valid module role" response, which only fires once
    # authorization has already passed — confirms the caller reached the
    # endpoint body at all, not the specific module-role validation logic
    # (already covered by test_module_contributed_roles.py).
    grant_roles_resp = client.post(
        f"/api/v1/orgs/{org['id']}/users/{target_id}/module-roles",
        json={"module_key": "nonexistent_module", "role_key": "nonexistent_role"},
        headers=auth_headers(grant_roles_token),
    )
    assert grant_roles_resp.status_code == 400, grant_roles_resp.text

    plain_resp = client.post(
        f"/api/v1/orgs/{org['id']}/users/{target_id}/module-roles",
        json={"module_key": "nonexistent_module", "role_key": "nonexistent_role"},
        headers=auth_headers(plain_token),
    )
    assert plain_resp.status_code == 403, plain_resp.text

    revoke_resp = client.delete(
        f"/api/v1/orgs/{org['id']}/users/{target_id}/module-roles/nonexistent_module/nonexistent_role",
        headers=auth_headers(grant_roles_token),
    )
    assert revoke_resp.status_code == 204, revoke_resp.text  # no-op, absent grant

    plain_revoke_resp = client.delete(
        f"/api/v1/orgs/{org['id']}/users/{target_id}/module-roles/nonexistent_module/nonexistent_role",
        headers=auth_headers(plain_token),
    )
    assert plain_revoke_resp.status_code == 403


def test_assign_project_role_gate_widened(client, admin_token):
    org, org_admin_token = create_org_admin_in(client, admin_token, "Project Role Wiring Org")
    project = create_project(client, org_admin_token, org["id"])
    target_id = create_org_user(client, org_admin_token, org["id"], "project_role_target@example.com", role="member")
    _plain_id = create_org_user(client, org_admin_token, org["id"], "project_role_plain@example.com", role="member")
    plain_token = login(client, "project_role_plain@example.com", "Password123!")
    _holder_id, grant_roles_token = _grant_roles_only_user(client, org_admin_token, org)

    ok_resp = client.post(
        f"/api/v1/projects/{project['id']}/roles", json={"user_id": target_id, "role": "member"},
        headers=auth_headers(grant_roles_token),
    )
    assert ok_resp.status_code == 204, ok_resp.text

    plain_resp = client.post(
        f"/api/v1/projects/{project['id']}/roles", json={"user_id": target_id, "role": "stakeholder"},
        headers=auth_headers(plain_token),
    )
    assert plain_resp.status_code == 403

    revoke_resp = client.delete(
        f"/api/v1/projects/{project['id']}/roles/{target_id}/member", headers=auth_headers(grant_roles_token)
    )
    assert revoke_resp.status_code == 204, revoke_resp.text


def test_assign_group_project_role_gate_widened(client, admin_token):
    org, org_admin_token = create_org_admin_in(client, admin_token, "Group Project Role Wiring Org")
    project = create_project(client, org_admin_token, org["id"])
    group_resp = client.post(
        f"/api/v1/orgs/{org['id']}/groups", json={"name": "Project Role Group"}, headers=auth_headers(org_admin_token)
    )
    group_id = group_resp.json()["id"]
    _holder_id, grant_roles_token = _grant_roles_only_user(client, org_admin_token, org)
    _plain_id = create_org_user(client, org_admin_token, org["id"], "group_project_role_plain@example.com", role="member")
    plain_token = login(client, "group_project_role_plain@example.com", "Password123!")

    ok_resp = client.post(
        f"/api/v1/projects/{project['id']}/group-roles", json={"org_group_id": group_id, "role": "member"},
        headers=auth_headers(grant_roles_token),
    )
    assert ok_resp.status_code == 204, ok_resp.text

    plain_resp = client.post(
        f"/api/v1/projects/{project['id']}/group-roles", json={"org_group_id": group_id, "role": "stakeholder"},
        headers=auth_headers(plain_token),
    )
    assert plain_resp.status_code == 403

    revoke_resp = client.delete(
        f"/api/v1/projects/{project['id']}/group-roles/{group_id}/member", headers=auth_headers(grant_roles_token)
    )
    assert revoke_resp.status_code == 204, revoke_resp.text


def test_assign_project_module_role_gate_widened(client, admin_token):
    org, org_admin_token = create_org_admin_in(client, admin_token, "Project Module Role Wiring Org")
    project = create_project(client, org_admin_token, org["id"])
    target_id = create_org_user(client, org_admin_token, org["id"], "project_module_role_target@example.com", role="member")
    _plain_id = create_org_user(client, org_admin_token, org["id"], "project_module_role_plain@example.com", role="member")
    plain_token = login(client, "project_module_role_plain@example.com", "Password123!")
    _holder_id, grant_roles_token = _grant_roles_only_user(client, org_admin_token, org)

    grant_roles_resp = client.post(
        f"/api/v1/projects/{project['id']}/members/{target_id}/module-roles",
        json={"module_key": "nonexistent_module", "role_key": "nonexistent_role"},
        headers=auth_headers(grant_roles_token),
    )
    assert grant_roles_resp.status_code == 400, grant_roles_resp.text  # reached body, rejected on module validity

    plain_resp = client.post(
        f"/api/v1/projects/{project['id']}/members/{target_id}/module-roles",
        json={"module_key": "nonexistent_module", "role_key": "nonexistent_role"},
        headers=auth_headers(plain_token),
    )
    assert plain_resp.status_code == 403

    revoke_resp = client.delete(
        f"/api/v1/projects/{project['id']}/members/{target_id}/module-roles/nonexistent_module/nonexistent_role",
        headers=auth_headers(grant_roles_token),
    )
    assert revoke_resp.status_code == 204  # no-op, absent grant

    plain_revoke_resp = client.delete(
        f"/api/v1/projects/{project['id']}/members/{target_id}/module-roles/nonexistent_module/nonexistent_role",
        headers=auth_headers(plain_token),
    )
    assert plain_revoke_resp.status_code == 403
