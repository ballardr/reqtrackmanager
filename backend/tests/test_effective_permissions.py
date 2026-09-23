"""Tests for Fine-Grained Access Control's Phase 2
(`docs/plans/core-fine-grained-access-control-plan.md`): `get_effective_
permissions`, `permission_satisfied`'s sub-type wildcard composition rule,
and the `require_permission` FastAPI dependency factory — the resolution
engine Phase 1's data model (`test_custom_roles.py`) was inert without.

Covers, in order: the static fixed-role mapping (Design Principle 3, zero
behavioural change for an org that never touches custom roles), direct and
group custom-role grants at both `"org"` and `"project"` scope (including
tenant isolation across organisations), the optional `ModuleRoleDefinition.
permissions` field, the sub-type wildcard rule, and `require_permission`
itself (server-admin bypass, path-derived scope resolution, 403 on
insufficient permission).
"""

import uuid as uuid_lib
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.database import SessionLocal
from app.models.custom_role import CustomRoleDefinition, CustomRolePermission, GroupCustomRoleGrant, UserCustomRoleGrant
from app.models.enums import PermissionLevel
from app.models.module_role import UserModuleRole
from app.models.organization import OrgGroup, OrgGroupMember
from app.models.user import User
from app.modules import registry as module_registry
from app.modules.registry import ModuleDefinition, ModuleRoleDefinition, build_registry
from app.services.permissions import ADMINISTRATIVE_PERMISSIONS, encode_permission
from app.services.rbac import get_effective_permissions, permission_satisfied, require_permission
from tests.conftest import auth_headers, create_org_admin_in, create_org_user, create_project

FAKE_MODULE_KEY = "fake_permissions_test_module"
FAKE_ROLE_KEY = "test_permission_role"


class _FakeRequest:
    """Minimal stand-in for FastAPI's `Request` — enough for `check_pat_
    scope`/`check_pat_project_scope`'s `getattr(request.state, ..., None)`
    reads to behave like an ordinary session request, plus a settable
    `path_params` dict for `require_permission`'s own path-derived
    resolution (mirrors `test_module_contributed_roles.py`'s identical
    fixture, extended with `path_params` since `require_permission`,
    unlike `require_module_role`, reads its scope ids off the request
    rather than as direct function arguments — see that dependency's own
    docstring for why)."""

    def __init__(self, path_params: dict | None = None):
        self.state = SimpleNamespace()
        self.path_params = path_params or {}


@pytest.fixture
def fake_module():
    """Registers a fake module with one project-scoped role declaring a
    `permissions` entry, for testing Phase 2's module-role-permissions
    union — mirrors `test_module_contributed_roles.py`'s own fixture
    mechanics exactly (mutate `INSTALLED_MODULES` in place, rebuild the
    registry cache, always tear down)."""
    definition = ModuleDefinition(
        key=FAKE_MODULE_KEY, name="Fake Permissions Test Module",
        description="A fixture module registered only for this test file's own assertions.",
        version="0.0.1", default_enabled=True, implemented=False, get_router=lambda: None,
        roles=(
            ModuleRoleDefinition(
                role_key=FAKE_ROLE_KEY, name="Test Permission Role",
                description="A project-scoped fixture role declaring `permissions`.", scope="project",
                permissions=(encode_permission("requirement", PermissionLevel.MANAGE.value),),
            ),
        ),
    )
    module_registry.INSTALLED_MODULES.append(definition)
    build_registry(force=True)
    yield FAKE_MODULE_KEY
    module_registry.INSTALLED_MODULES[:] = [m for m in module_registry.INSTALLED_MODULES if m.key != FAKE_MODULE_KEY]
    build_registry(force=True)


def _user_id(client, token) -> uuid_lib.UUID:
    return uuid_lib.UUID(client.get("/api/v1/auth/me", headers=auth_headers(token)).json()["id"])


def _set_project_role(client, admin_token, project_id, user_id, role) -> None:
    resp = client.post(
        f"/api/v1/projects/{project_id}/roles", json={"user_id": str(user_id), "role": role},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code in (200, 201, 204), resp.text


# --- Static fixed-role mapping (Design Principle 3) --------------------------


def test_org_admin_has_administrative_but_no_artefact_permissions(client, admin_token):
    org, org_admin_token = create_org_admin_in(client, admin_token, "Org Admin Permission Mapping Org")
    user_id = _user_id(client, org_admin_token)

    db = SessionLocal()
    try:
        held = get_effective_permissions(db, user_id, organization_id=uuid_lib.UUID(org["id"]))
    finally:
        db.close()

    for admin_key in ADMINISTRATIVE_PERMISSIONS:
        assert admin_key in held
    # C-U-01: "No Project access is guaranteed from any roles apart from
    # org admin being able to manage project settings" — org admin gets no
    # artefact-type permission from this mapping.
    assert encode_permission("requirement", PermissionLevel.VIEW.value) not in held


def test_project_manager_has_every_artefact_permission_at_every_level(client, admin_token):
    org, org_admin_token = create_org_admin_in(client, admin_token, "Project Manager Permission Mapping Org")
    project = create_project(client, org_admin_token, org["id"])
    # The project creator defaults to project manager (C-U-10).
    user_id = _user_id(client, org_admin_token)

    db = SessionLocal()
    try:
        held = get_effective_permissions(db, user_id, project_id=uuid_lib.UUID(project["id"]))
    finally:
        db.close()

    for level in PermissionLevel:
        assert encode_permission("requirement", level.value) in held
        assert encode_permission("decision", level.value) in held
    # Point 1 of `get_effective_permissions`'s own docstring: the caller's
    # effective OrgRoles (here, ORG_ADMIN) are resolved even for a
    # project-scoped call, so administrative atoms are visible too.
    for admin_key in ADMINISTRATIVE_PERMISSIONS:
        assert admin_key in held


def test_project_member_has_view_only(client, admin_token):
    org, org_admin_token = create_org_admin_in(client, admin_token, "Project Member Permission Mapping Org")
    project = create_project(client, org_admin_token, org["id"])
    member_id = create_org_user(client, org_admin_token, org["id"], "plain_member@example.com", role="member")
    _set_project_role(client, org_admin_token, project["id"], member_id, "member")

    db = SessionLocal()
    try:
        held = get_effective_permissions(db, uuid_lib.UUID(member_id), project_id=uuid_lib.UUID(project["id"]))
    finally:
        db.close()

    assert encode_permission("requirement", PermissionLevel.VIEW.value) in held
    assert encode_permission("requirement", PermissionLevel.PROPOSE_CREATE.value) not in held
    assert encode_permission("requirement", PermissionLevel.MANAGE.value) not in held
    assert not (held & set(ADMINISTRATIVE_PERMISSIONS))


def test_project_stakeholder_has_view_and_propose_create_only(client, admin_token):
    org, org_admin_token = create_org_admin_in(client, admin_token, "Stakeholder Permission Mapping Org")
    project = create_project(client, org_admin_token, org["id"])
    stakeholder_id = create_org_user(client, org_admin_token, org["id"], "stakeholder@example.com", role="member")
    _set_project_role(client, org_admin_token, project["id"], stakeholder_id, "stakeholder")

    db = SessionLocal()
    try:
        held = get_effective_permissions(db, uuid_lib.UUID(stakeholder_id), project_id=uuid_lib.UUID(project["id"]))
    finally:
        db.close()

    assert encode_permission("requirement", PermissionLevel.VIEW.value) in held
    assert encode_permission("requirement", PermissionLevel.PROPOSE_CREATE.value) in held
    assert encode_permission("requirement", PermissionLevel.MANAGE.value) not in held
    assert encode_permission("requirement", PermissionLevel.APPROVE_BASELINE.value) not in held


def test_no_scope_resolves_to_empty_set(client, admin_token):
    org, org_admin_token = create_org_admin_in(client, admin_token, "No Scope Org")
    user_id = _user_id(client, org_admin_token)
    db = SessionLocal()
    try:
        assert get_effective_permissions(db, user_id) == set()
        # A nonexistent project resolves no organisation either.
        assert get_effective_permissions(db, user_id, project_id=uuid_lib.uuid4()) == set()
    finally:
        db.close()


# --- Custom-role grants (direct + group, org- and project-scoped) -----------


def test_direct_org_scoped_custom_role_grant_applies_throughout_the_org(client, admin_token):
    org, org_admin_token = create_org_admin_in(client, admin_token, "Org Scoped Custom Role Org")
    project_a = create_project(client, org_admin_token, org["id"], "Project A")
    project_b = create_project(client, org_admin_token, org["id"], "Project B")
    grantee_id = create_org_user(client, org_admin_token, org["id"], "org_scoped_grantee@example.com", role="member")

    db = SessionLocal()
    try:
        role = CustomRoleDefinition(organization_id=org["id"], name="Org Reviewer", description="", scope="org")
        db.add(role)
        db.flush()
        permission = encode_permission("decision", PermissionLevel.APPROVE_BASELINE.value)
        db.add(CustomRolePermission(custom_role_id=role.id, permission=permission))
        db.add(UserCustomRoleGrant(user_id=uuid_lib.UUID(grantee_id), custom_role_id=role.id, organization_id=org["id"]))
        db.commit()

        # An org-scoped custom role's grant is visible at org scope...
        held_org = get_effective_permissions(db, uuid_lib.UUID(grantee_id), organization_id=uuid_lib.UUID(org["id"]))
        assert permission in held_org
        # ...and at every project within that same organisation (Design
        # decision recorded in `_custom_role_ids_for_scope`'s own docstring).
        held_a = get_effective_permissions(db, uuid_lib.UUID(grantee_id), project_id=uuid_lib.UUID(project_a["id"]))
        held_b = get_effective_permissions(db, uuid_lib.UUID(grantee_id), project_id=uuid_lib.UUID(project_b["id"]))
        assert permission in held_a
        assert permission in held_b
    finally:
        db.rollback()
        db.close()


def test_project_scoped_custom_role_grant_is_scoped_to_that_project_only(client, admin_token):
    org, org_admin_token = create_org_admin_in(client, admin_token, "Project Scoped Custom Role Org")
    project_a = create_project(client, org_admin_token, org["id"], "Project A")
    project_b = create_project(client, org_admin_token, org["id"], "Project B")
    grantee_id = create_org_user(
        client, org_admin_token, org["id"], "project_scoped_grantee@example.com", role="member"
    )

    db = SessionLocal()
    try:
        role = CustomRoleDefinition(organization_id=org["id"], name="Project Reviewer", description="", scope="project")
        db.add(role)
        db.flush()
        permission = encode_permission("requirement", PermissionLevel.MANAGE.value)
        db.add(CustomRolePermission(custom_role_id=role.id, permission=permission))
        db.add(
            UserCustomRoleGrant(
                user_id=uuid_lib.UUID(grantee_id), custom_role_id=role.id,
                organization_id=org["id"], project_id=project_a["id"],
            )
        )
        db.commit()

        held_a = get_effective_permissions(db, uuid_lib.UUID(grantee_id), project_id=uuid_lib.UUID(project_a["id"]))
        held_b = get_effective_permissions(db, uuid_lib.UUID(grantee_id), project_id=uuid_lib.UUID(project_b["id"]))
        held_org = get_effective_permissions(db, uuid_lib.UUID(grantee_id), organization_id=uuid_lib.UUID(org["id"]))
        assert permission in held_a
        assert permission not in held_b
        assert permission not in held_org
    finally:
        db.rollback()
        db.close()


def test_custom_role_grant_never_leaks_across_organisations(client, admin_token):
    org_a, org_a_admin_token = create_org_admin_in(client, admin_token, "Tenant Isolation Org A")
    org_b, _ = create_org_admin_in(client, admin_token, "Tenant Isolation Org B")
    grantee_id = create_org_user(client, org_a_admin_token, org_a["id"], "isolated_grantee@example.com", role="member")

    db = SessionLocal()
    try:
        role = CustomRoleDefinition(organization_id=org_a["id"], name="A-Only Role", description="", scope="org")
        db.add(role)
        db.flush()
        permission = encode_permission("requirement", PermissionLevel.VIEW.value)
        db.add(CustomRolePermission(custom_role_id=role.id, permission=permission))
        db.add(UserCustomRoleGrant(user_id=uuid_lib.UUID(grantee_id), custom_role_id=role.id, organization_id=org_a["id"]))
        db.commit()

        held_a = get_effective_permissions(db, uuid_lib.UUID(grantee_id), organization_id=uuid_lib.UUID(org_a["id"]))
        held_b = get_effective_permissions(db, uuid_lib.UUID(grantee_id), organization_id=uuid_lib.UUID(org_b["id"]))
        assert permission in held_a
        assert permission not in held_b
    finally:
        db.rollback()
        db.close()


def test_group_custom_role_grant_via_transitive_org_group_membership(client, admin_token):
    org, org_admin_token = create_org_admin_in(client, admin_token, "Group Custom Role Org")
    project = create_project(client, org_admin_token, org["id"])
    member_id = create_org_user(client, org_admin_token, org["id"], "group_member@example.com", role="member")

    db = SessionLocal()
    try:
        parent_group = OrgGroup(organization_id=org["id"], name="Parent Group")
        child_group = OrgGroup(organization_id=org["id"], name="Child Group")
        db.add_all([parent_group, child_group])
        db.flush()
        # The user is only a direct member of the *child* group, nested
        # inside the parent — `get_user_org_group_ids` resolves the parent
        # as an inherited ancestor, so a grant made to the parent should
        # still reach the user (mirrors `_has_module_role_grant`'s own
        # descendant-expansion, applied here via the ancestor direction).
        db.add(OrgGroupMember(org_group_id=child_group.id, user_id=uuid_lib.UUID(member_id)))
        db.add(OrgGroupMember(org_group_id=parent_group.id, member_org_group_id=child_group.id))
        db.flush()

        role = CustomRoleDefinition(organization_id=org["id"], name="Group Reviewer", description="", scope="project")
        db.add(role)
        db.flush()
        permission = encode_permission("change_request", PermissionLevel.PROPOSE_CREATE.value)
        db.add(CustomRolePermission(custom_role_id=role.id, permission=permission))
        db.add(
            GroupCustomRoleGrant(
                org_group_id=parent_group.id, custom_role_id=role.id,
                organization_id=org["id"], project_id=project["id"],
            )
        )
        db.commit()

        held = get_effective_permissions(db, uuid_lib.UUID(member_id), project_id=uuid_lib.UUID(project["id"]))
        assert permission in held
    finally:
        db.rollback()
        db.close()


# --- Module-contributed roles' `permissions` field ---------------------------


def test_module_role_permissions_field_is_unioned_in(client, admin_token, fake_module):
    org, org_admin_token = create_org_admin_in(client, admin_token, "Module Role Permission Field Org")
    project = create_project(client, org_admin_token, org["id"])
    grantee_id = create_org_user(client, org_admin_token, org["id"], "module_role_grantee@example.com", role="member")

    db = SessionLocal()
    try:
        db.add(
            UserModuleRole(
                user_id=uuid_lib.UUID(grantee_id), module_key=fake_module, role_key=FAKE_ROLE_KEY,
                organization_id=org["id"], project_id=project["id"],
            )
        )
        db.commit()

        held = get_effective_permissions(db, uuid_lib.UUID(grantee_id), project_id=uuid_lib.UUID(project["id"]))
        assert encode_permission("requirement", PermissionLevel.MANAGE.value) in held
    finally:
        db.rollback()
        db.close()


def test_module_role_permissions_field_absent_when_module_disabled(client, admin_token, fake_module):
    from app.models.module import OrganizationModuleEnablement

    org, org_admin_token = create_org_admin_in(client, admin_token, "Disabled Module Permission Field Org")
    project = create_project(client, org_admin_token, org["id"])
    grantee_id = create_org_user(client, org_admin_token, org["id"], "disabled_module_grantee@example.com", role="member")

    db = SessionLocal()
    try:
        db.add(
            UserModuleRole(
                user_id=uuid_lib.UUID(grantee_id), module_key=fake_module, role_key=FAKE_ROLE_KEY,
                organization_id=org["id"], project_id=project["id"],
            )
        )
        db.add(OrganizationModuleEnablement(organization_id=org["id"], module_key=fake_module, enabled=False))
        db.commit()

        held = get_effective_permissions(db, uuid_lib.UUID(grantee_id), project_id=uuid_lib.UUID(project["id"]))
        assert encode_permission("requirement", PermissionLevel.MANAGE.value) not in held
    finally:
        db.rollback()
        db.close()


# --- Sub-type wildcard composition (Phase 0 Q3) -------------------------------


def test_permission_satisfied_wildcard_composition():
    wildcard = encode_permission("decision", PermissionLevel.APPROVE_BASELINE.value)
    specific = encode_permission("decision", PermissionLevel.APPROVE_BASELINE.value, "Architecture")
    other_specific = encode_permission("decision", PermissionLevel.APPROVE_BASELINE.value, "Cost")

    # A broader, unscoped grant satisfies any specific sub-type check.
    assert permission_satisfied({wildcard}, specific)
    assert permission_satisfied({wildcard}, other_specific)
    # Exact match always satisfies.
    assert permission_satisfied({specific}, specific)
    # The reverse never holds: a specific grant satisfies neither the
    # wildcard nor a *different* specific sub-type.
    assert not permission_satisfied({specific}, wildcard)
    assert not permission_satisfied({specific}, other_specific)
    # Administrative permissions have no wildcard concept.
    assert permission_satisfied({"grant_roles"}, "grant_roles")
    assert not permission_satisfied(set(), "grant_roles")


# --- `require_permission` dependency ------------------------------------------


def test_require_permission_server_admin_bypasses(client, admin_token):
    db = SessionLocal()
    try:
        admin_user = db.query(User).filter(User.email == "admin@example.com").first()
        dependency = require_permission("grant_roles")
        result = dependency(request=_FakeRequest(path_params={}), current_user=admin_user, db=db)
        assert result.id == admin_user.id
    finally:
        db.close()


def test_require_permission_project_scoped_check(client, admin_token):
    org, org_admin_token = create_org_admin_in(client, admin_token, "Require Permission Project Org")
    project = create_project(client, org_admin_token, org["id"])
    member_id = create_org_user(client, org_admin_token, org["id"], "require_perm_member@example.com", role="member")
    _set_project_role(client, org_admin_token, project["id"], member_id, "member")
    project_uuid = uuid_lib.UUID(project["id"])

    db = SessionLocal()
    try:
        member_user = db.get(User, uuid_lib.UUID(member_id))

        # A plain member holds VIEW but not MANAGE.
        view_dependency = require_permission(encode_permission("requirement", PermissionLevel.VIEW.value))
        result = view_dependency(
            request=_FakeRequest(path_params={"project_id": str(project_uuid)}), current_user=member_user, db=db
        )
        assert result.id == member_user.id

        manage_dependency = require_permission(encode_permission("requirement", PermissionLevel.MANAGE.value))
        with pytest.raises(HTTPException) as exc_info:
            manage_dependency(
                request=_FakeRequest(path_params={"project_id": str(project_uuid)}), current_user=member_user, db=db
            )
        assert exc_info.value.status_code == 403
    finally:
        db.close()


def test_require_permission_org_scoped_check_via_grant_roles(client, admin_token):
    org, org_admin_token = create_org_admin_in(client, admin_token, "Require Permission Grant Roles Org")
    org_uuid = uuid_lib.UUID(org["id"])
    org_admin_user_id = _user_id(client, org_admin_token)
    plain_id = create_org_user(client, org_admin_token, org["id"], "require_perm_plain@example.com", role="member")

    db = SessionLocal()
    try:
        dependency = require_permission("grant_roles")

        # ORG_ADMIN's own administrative-permission mapping satisfies it.
        org_admin_user = db.get(User, org_admin_user_id)
        result = dependency(
            request=_FakeRequest(path_params={"organization_id": str(org_uuid)}), current_user=org_admin_user, db=db
        )
        assert result.id == org_admin_user.id

        # A plain org member holds no administrative permission.
        plain_user = db.get(User, uuid_lib.UUID(plain_id))
        with pytest.raises(HTTPException) as exc_info:
            dependency(
                request=_FakeRequest(path_params={"organization_id": str(org_uuid)}), current_user=plain_user, db=db
            )
        assert exc_info.value.status_code == 403
    finally:
        db.close()


def test_require_permission_raises_construction_error_without_scope_path_param(client, admin_token):
    db = SessionLocal()
    try:
        plain_id = None
        org, org_admin_token = create_org_admin_in(client, admin_token, "Require Permission No Scope Org")
        plain_id = create_org_user(client, org_admin_token, org["id"], "require_perm_no_scope@example.com", role="member")
        plain_user = db.get(User, uuid_lib.UUID(plain_id))

        dependency = require_permission("grant_roles")
        with pytest.raises(HTTPException) as exc_info:
            dependency(request=_FakeRequest(path_params={}), current_user=plain_user, db=db)
        assert exc_info.value.status_code == 500
    finally:
        db.close()
