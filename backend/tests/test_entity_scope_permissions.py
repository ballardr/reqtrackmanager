"""Tests for Fine-Grained Access Control (core) plan Phase 5
(`docs/plans/core-fine-grained-access-control-plan.md`): the generic
module-owned entity-scope registry (`EntityScopeDefinition`,
`get_all_registered_entity_scopes`), `CustomRoleDefinition.scope`'s
widened validation, `UserCustomRoleGrant`/`GroupCustomRoleGrant.
scope_entity_id`, `get_effective_permissions`/`require_permission`'s new
`entity_scope`/`entity_id` parameters, and the `GET /orgs/{id}/entity-scopes`
endpoint.

Covers, in order: the registry mechanism itself (via a fixture module,
isolated from any real module), a module-role entity-scoped grant's
`permissions` composing only when `entity_scope`/`entity_id` are given (and
never leaking into a plain org/project check — the same exclusion
`_module_role_pairs_for_scope` already had), the identical shape for a
custom-role entity-scoped grant (including the leak this phase's own
implementation had to guard against explicitly, since `scope_entity_id` and
`project_id` are both `NULL` for different reasons), tenant isolation across
the grant endpoints, and `require_permission`'s own `entity_scope` handling.
Compliance's real `"standard"` scope (registered in `app.modules.compliance.
module`) is used for the HTTP-level API tests, since it's the first real
consumer this phase's own scope registers; the lower-level resolution-engine
tests use an isolated fixture module instead, mirroring `test_effective_
permissions.py`'s own `fake_module` fixture one tier up.
"""

from __future__ import annotations

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
from app.modules.registry import (
    EntityScopeDefinition,
    ModuleDefinition,
    ModuleRoleDefinition,
    build_registry,
    get_all_registered_entity_scopes,
)
from app.services.permissions import encode_permission
from app.services.rbac import get_effective_permissions, require_permission
from tests.conftest import auth_headers, create_org_admin_in, create_org_user, login

FAKE_MODULE_KEY = "fake_entity_scope_test_module"
FAKE_ROLE_KEY = "fake_entity_scope_test_role"
# `CustomRoleDefinition.scope`/`ModuleRoleDefinitionRow.scope` are both
# `String(20)` (a pre-existing, system-wide constraint on scope strings,
# unrelated to this phase) — kept within that bound like every real
# registered scope (e.g. compliance's `"standard"`).
FAKE_SCOPE_KEY = "fake_test_scope"

# Keyed by fake entity id -> owning organisation id, mutated per-test by the
# `fake_entity_scope_module` fixture's caller — lets the fixture's
# `resolve_organization_id`/`list_entities` behave like a real module-owned
# table without needing one.
_fake_entities: dict[uuid_lib.UUID, uuid_lib.UUID] = {}


def _resolve_fake_entity_org(db, entity_id):
    return _fake_entities.get(entity_id)


def _list_fake_entities(db, organization_id):
    return [(eid, f"Fake Entity {eid}") for eid, org_id in _fake_entities.items() if org_id == organization_id]


class _FakeRequest:
    """Mirrors `test_effective_permissions.py`'s own identical fixture."""

    def __init__(self, path_params: dict | None = None):
        self.state = SimpleNamespace()
        self.path_params = path_params or {}


@pytest.fixture
def fake_entity_scope_module():
    """Registers a fixture module declaring one entity-scoped role plus a
    matching `entity_scopes` registration, isolated from any real module —
    mirrors `test_effective_permissions.py`'s `fake_module` fixture exactly."""
    _fake_entities.clear()
    definition = ModuleDefinition(
        key=FAKE_MODULE_KEY, name="Fake Entity Scope Test Module",
        description="A fixture module registered only for this test file's own assertions.",
        version="0.0.1", default_enabled=True, implemented=False, get_router=lambda: None,
        roles=(
            ModuleRoleDefinition(
                role_key=FAKE_ROLE_KEY, name="Fake Entity Scope Test Role",
                description="An entity-scoped fixture role declaring `permissions`.", scope=FAKE_SCOPE_KEY,
                resolve_entity_organization_id=_resolve_fake_entity_org,
                permissions=(encode_permission("requirement", PermissionLevel.MANAGE.value),),
            ),
        ),
        entity_scopes={
            FAKE_SCOPE_KEY: EntityScopeDefinition(
                resolve_organization_id=_resolve_fake_entity_org, label="Fake Entity", list_entities=_list_fake_entities
            ),
        },
    )
    module_registry.INSTALLED_MODULES.append(definition)
    build_registry(force=True)
    yield FAKE_MODULE_KEY
    module_registry.INSTALLED_MODULES[:] = [m for m in module_registry.INSTALLED_MODULES if m.key != FAKE_MODULE_KEY]
    build_registry(force=True)
    _fake_entities.clear()


def _user_id(client, token) -> uuid_lib.UUID:
    return uuid_lib.UUID(client.get("/api/v1/auth/me", headers=auth_headers(token)).json()["id"])


def _create_standard(client, token, org_id, *, reference="ISO-27001", name="Corporate Security Standard"):
    resp = client.post(
        f"/api/v1/orgs/{org_id}/modules/compliance/standards",
        json={"reference": reference, "name": name, "initial_version_label": "1.0"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# --- The registry itself ------------------------------------------------


def test_get_all_registered_entity_scopes_includes_fixture_scope(fake_entity_scope_module):
    scopes = get_all_registered_entity_scopes()
    assert FAKE_SCOPE_KEY in scopes
    assert scopes[FAKE_SCOPE_KEY].label == "Fake Entity"


def test_get_all_registered_entity_scopes_includes_compliance_standard():
    scopes = get_all_registered_entity_scopes()
    assert "standard" in scopes
    assert scopes["standard"].label == "Standard"


# --- Module-role entity-scoped `permissions` composition -----------------


def test_module_role_entity_scope_permission_composes_only_with_entity_scope_given(client, admin_token, fake_entity_scope_module):
    org, org_admin_token = create_org_admin_in(client, admin_token, "Module Role Entity Scope Org")
    grantee_id = create_org_user(client, org_admin_token, org["id"], "module_entity_grantee@example.com", role="member")
    entity_id = uuid_lib.uuid4()
    _fake_entities[entity_id] = uuid_lib.UUID(org["id"])

    db = SessionLocal()
    try:
        db.add(
            UserModuleRole(
                user_id=uuid_lib.UUID(grantee_id), module_key=FAKE_MODULE_KEY, role_key=FAKE_ROLE_KEY,
                organization_id=org["id"], scope_entity_id=entity_id,
            )
        )
        db.commit()

        permission = encode_permission("requirement", PermissionLevel.MANAGE.value)
        held_entity = get_effective_permissions(
            db, uuid_lib.UUID(grantee_id), organization_id=uuid_lib.UUID(org["id"]),
            entity_scope=FAKE_SCOPE_KEY, entity_id=entity_id,
        )
        assert permission in held_entity

        # Omitting entity_scope/entity_id — every pre-Phase-5 call site's
        # shape — must not see this grant at all (Design Principle 1).
        held_plain_org = get_effective_permissions(db, uuid_lib.UUID(grantee_id), organization_id=uuid_lib.UUID(org["id"]))
        assert permission not in held_plain_org

        # A different entity of the same scope must not see it either.
        other_entity_id = uuid_lib.uuid4()
        held_other_entity = get_effective_permissions(
            db, uuid_lib.UUID(grantee_id), organization_id=uuid_lib.UUID(org["id"]),
            entity_scope=FAKE_SCOPE_KEY, entity_id=other_entity_id,
        )
        assert permission not in held_other_entity
    finally:
        db.rollback()
        db.close()


# --- Custom-role entity-scoped grants -------------------------------------


def test_custom_role_entity_scope_grant_composes_only_with_entity_scope_given(client, admin_token, fake_entity_scope_module):
    org, org_admin_token = create_org_admin_in(client, admin_token, "Custom Role Entity Scope Org")
    grantee_id = create_org_user(client, org_admin_token, org["id"], "custom_entity_grantee@example.com", role="member")
    entity_id = uuid_lib.uuid4()
    _fake_entities[entity_id] = uuid_lib.UUID(org["id"])

    db = SessionLocal()
    try:
        role = CustomRoleDefinition(organization_id=org["id"], name="Fake Entity Reviewer", description="", scope=FAKE_SCOPE_KEY)
        db.add(role)
        db.flush()
        permission = encode_permission("decision", PermissionLevel.APPROVE_BASELINE.value)
        db.add(CustomRolePermission(custom_role_id=role.id, permission=permission))
        db.add(
            UserCustomRoleGrant(
                user_id=uuid_lib.UUID(grantee_id), custom_role_id=role.id,
                organization_id=org["id"], scope_entity_id=entity_id,
            )
        )
        db.commit()

        held_entity = get_effective_permissions(
            db, uuid_lib.UUID(grantee_id), organization_id=uuid_lib.UUID(org["id"]),
            entity_scope=FAKE_SCOPE_KEY, entity_id=entity_id,
        )
        assert permission in held_entity

        # This is the regression this phase's own implementation had to
        # guard against explicitly: `scope_entity_id` and `project_id` are
        # both NULL on this row for different reasons, so a plain org-scope
        # resolution must not misidentify it as an org-scoped grant.
        held_plain_org = get_effective_permissions(db, uuid_lib.UUID(grantee_id), organization_id=uuid_lib.UUID(org["id"]))
        assert permission not in held_plain_org

        other_entity_id = uuid_lib.uuid4()
        held_other_entity = get_effective_permissions(
            db, uuid_lib.UUID(grantee_id), organization_id=uuid_lib.UUID(org["id"]),
            entity_scope=FAKE_SCOPE_KEY, entity_id=other_entity_id,
        )
        assert permission not in held_other_entity
    finally:
        db.rollback()
        db.close()


def test_group_custom_role_entity_scope_grant_via_transitive_membership(client, admin_token, fake_entity_scope_module):
    org, org_admin_token = create_org_admin_in(client, admin_token, "Group Custom Role Entity Scope Org")
    member_id = create_org_user(client, org_admin_token, org["id"], "group_entity_member@example.com", role="member")
    entity_id = uuid_lib.uuid4()
    _fake_entities[entity_id] = uuid_lib.UUID(org["id"])

    db = SessionLocal()
    try:
        group = OrgGroup(organization_id=org["id"], name="Entity Reviewers Group")
        db.add(group)
        db.flush()
        db.add(OrgGroupMember(org_group_id=group.id, user_id=uuid_lib.UUID(member_id)))

        role = CustomRoleDefinition(organization_id=org["id"], name="Group Entity Reviewer", description="", scope=FAKE_SCOPE_KEY)
        db.add(role)
        db.flush()
        permission = encode_permission("change_request", PermissionLevel.VIEW.value)
        db.add(CustomRolePermission(custom_role_id=role.id, permission=permission))
        db.add(
            GroupCustomRoleGrant(
                org_group_id=group.id, custom_role_id=role.id, organization_id=org["id"], scope_entity_id=entity_id,
            )
        )
        db.commit()

        held = get_effective_permissions(
            db, uuid_lib.UUID(member_id), organization_id=uuid_lib.UUID(org["id"]),
            entity_scope=FAKE_SCOPE_KEY, entity_id=entity_id,
        )
        assert permission in held
    finally:
        db.rollback()
        db.close()


def test_custom_role_entity_scope_grant_never_leaks_across_organisations(client, admin_token, fake_entity_scope_module):
    org_a, org_a_admin_token = create_org_admin_in(client, admin_token, "Entity Scope Tenant Isolation Org A")
    org_b, _ = create_org_admin_in(client, admin_token, "Entity Scope Tenant Isolation Org B")
    grantee_id = create_org_user(client, org_a_admin_token, org_a["id"], "entity_isolated_grantee@example.com", role="member")
    entity_id = uuid_lib.uuid4()
    _fake_entities[entity_id] = uuid_lib.UUID(org_a["id"])

    db = SessionLocal()
    try:
        role = CustomRoleDefinition(organization_id=org_a["id"], name="A-Only Entity Role", description="", scope=FAKE_SCOPE_KEY)
        db.add(role)
        db.flush()
        permission = encode_permission("requirement", PermissionLevel.VIEW.value)
        db.add(CustomRolePermission(custom_role_id=role.id, permission=permission))
        db.add(
            UserCustomRoleGrant(
                user_id=uuid_lib.UUID(grantee_id), custom_role_id=role.id,
                organization_id=org_a["id"], scope_entity_id=entity_id,
            )
        )
        db.commit()

        held_a = get_effective_permissions(
            db, uuid_lib.UUID(grantee_id), organization_id=uuid_lib.UUID(org_a["id"]),
            entity_scope=FAKE_SCOPE_KEY, entity_id=entity_id,
        )
        held_b = get_effective_permissions(
            db, uuid_lib.UUID(grantee_id), organization_id=uuid_lib.UUID(org_b["id"]),
            entity_scope=FAKE_SCOPE_KEY, entity_id=entity_id,
        )
        assert permission in held_a
        assert permission not in held_b
    finally:
        db.rollback()
        db.close()


# --- `require_permission`'s `entity_scope` parameter ----------------------


def test_require_permission_entity_scope_check(client, admin_token, fake_entity_scope_module):
    org, org_admin_token = create_org_admin_in(client, admin_token, "Require Permission Entity Scope Org")
    grantee_id = create_org_user(client, org_admin_token, org["id"], "require_perm_entity_grantee@example.com", role="member")
    entity_id = uuid_lib.uuid4()
    _fake_entities[entity_id] = uuid_lib.UUID(org["id"])

    db = SessionLocal()
    try:
        db.add(
            UserModuleRole(
                user_id=uuid_lib.UUID(grantee_id), module_key=FAKE_MODULE_KEY, role_key=FAKE_ROLE_KEY,
                organization_id=org["id"], scope_entity_id=entity_id,
            )
        )
        db.commit()

        grantee_user = db.get(User, uuid_lib.UUID(grantee_id))
        dependency = require_permission(
            encode_permission("requirement", PermissionLevel.MANAGE.value), entity_scope=FAKE_SCOPE_KEY
        )
        result = dependency(
            request=_FakeRequest(path_params={f"{FAKE_SCOPE_KEY}_id": str(entity_id)}), current_user=grantee_user, db=db
        )
        assert result.id == grantee_user.id

        # A different, unheld permission still 403s.
        other_dependency = require_permission("grant_roles", entity_scope=FAKE_SCOPE_KEY)
        with pytest.raises(HTTPException) as exc_info:
            other_dependency(
                request=_FakeRequest(path_params={f"{FAKE_SCOPE_KEY}_id": str(entity_id)}), current_user=grantee_user, db=db
            )
        assert exc_info.value.status_code == 403
    finally:
        db.close()


def test_require_permission_entity_scope_404s_on_unknown_entity(client, admin_token, fake_entity_scope_module):
    org, org_admin_token = create_org_admin_in(client, admin_token, "Require Permission Unknown Entity Org")
    plain_id = create_org_user(client, org_admin_token, org["id"], "require_perm_unknown_entity@example.com", role="member")

    db = SessionLocal()
    try:
        plain_user = db.get(User, uuid_lib.UUID(plain_id))
        dependency = require_permission("grant_roles", entity_scope=FAKE_SCOPE_KEY)
        with pytest.raises(HTTPException) as exc_info:
            dependency(
                request=_FakeRequest(path_params={f"{FAKE_SCOPE_KEY}_id": str(uuid_lib.uuid4())}),
                current_user=plain_user, db=db,
            )
        assert exc_info.value.status_code == 404
    finally:
        db.close()


def test_require_permission_unregistered_entity_scope_is_a_construction_error(client, admin_token):
    org, org_admin_token = create_org_admin_in(client, admin_token, "Require Permission Bad Scope Org")
    plain_id = create_org_user(client, org_admin_token, org["id"], "require_perm_bad_scope@example.com", role="member")

    db = SessionLocal()
    try:
        plain_user = db.get(User, uuid_lib.UUID(plain_id))
        dependency = require_permission("grant_roles", entity_scope="not_a_registered_scope")
        with pytest.raises(HTTPException) as exc_info:
            dependency(
                request=_FakeRequest(path_params={"not_a_registered_scope_id": str(uuid_lib.uuid4())}),
                current_user=plain_user, db=db,
            )
        assert exc_info.value.status_code == 500
    finally:
        db.close()


def test_require_permission_server_admin_bypasses_entity_scope_check(client, admin_token, fake_entity_scope_module):
    db = SessionLocal()
    try:
        admin_user = db.query(User).filter(User.email == "admin@example.com").first()
        dependency = require_permission("grant_roles", entity_scope=FAKE_SCOPE_KEY)
        result = dependency(
            request=_FakeRequest(path_params={f"{FAKE_SCOPE_KEY}_id": str(uuid_lib.uuid4())}), current_user=admin_user, db=db
        )
        assert result.id == admin_user.id
    finally:
        db.close()


# --- HTTP API: `GET /orgs/{id}/entity-scopes` + custom-role scope/grant ---
# validation, using compliance's real `"standard"` scope as the first real
# consumer this phase's own registry has.


def test_list_org_entity_scopes_includes_standard(client, admin_token):
    org, org_admin_token = create_org_admin_in(client, admin_token, "Entity Scopes Endpoint Org")
    standard = _create_standard(client, org_admin_token, org["id"])

    resp = client.get(f"/api/v1/orgs/{org['id']}/entity-scopes", headers=auth_headers(org_admin_token))
    assert resp.status_code == 200, resp.text
    scopes = {s["key"]: s for s in resp.json()}
    assert "standard" in scopes
    assert scopes["standard"]["label"] == "Standard"
    entity_ids = {e["id"] for e in scopes["standard"]["entities"]}
    assert standard["id"] in entity_ids


def test_create_custom_role_accepts_registered_entity_scope(client, admin_token):
    org, org_admin_token = create_org_admin_in(client, admin_token, "Custom Role Standard Scope Org")
    resp = client.post(
        f"/api/v1/orgs/{org['id']}/custom-roles",
        json={"name": "Standard Reviewer", "description": "", "scope": "standard", "permissions": []},
        headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["scope"] == "standard"


def test_create_custom_role_rejects_unregistered_scope(client, admin_token):
    org, org_admin_token = create_org_admin_in(client, admin_token, "Custom Role Bad Scope Org")
    resp = client.post(
        f"/api/v1/orgs/{org['id']}/custom-roles",
        json={"name": "Bad Scope Role", "description": "", "scope": "not_a_scope", "permissions": []},
        headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 400, resp.text


def test_grant_entity_scoped_custom_role_to_user_requires_and_validates_scope_entity_id(client, admin_token):
    org, org_admin_token = create_org_admin_in(client, admin_token, "Grant Standard Scope Org")
    other_org, other_org_admin_token = create_org_admin_in(client, admin_token, "Grant Standard Scope Other Org")
    standard = _create_standard(client, org_admin_token, org["id"])
    other_standard = _create_standard(client, other_org_admin_token, other_org["id"])
    grantee_id = create_org_user(client, org_admin_token, org["id"], "standard_grantee@example.com", role="member")

    role_resp = client.post(
        f"/api/v1/orgs/{org['id']}/custom-roles",
        json={"name": "Standard Grant Role", "description": "", "scope": "standard", "permissions": []},
        headers=auth_headers(org_admin_token),
    )
    assert role_resp.status_code == 201, role_resp.text
    role_id = role_resp.json()["id"]

    # Missing scope_entity_id -> 400.
    resp = client.post(
        f"/api/v1/orgs/{org['id']}/custom-roles/{role_id}/users/{grantee_id}",
        json={}, headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 400, resp.text

    # A standard belonging to a different organisation -> 400 (tenant isolation).
    resp = client.post(
        f"/api/v1/orgs/{org['id']}/custom-roles/{role_id}/users/{grantee_id}",
        json={"scope_entity_id": other_standard["id"]}, headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 400, resp.text

    # A standard in this organisation -> 204.
    resp = client.post(
        f"/api/v1/orgs/{org['id']}/custom-roles/{role_id}/users/{grantee_id}",
        json={"scope_entity_id": standard["id"]}, headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 204, resp.text

    db = SessionLocal()
    try:
        grant = db.query(UserCustomRoleGrant).filter(
            UserCustomRoleGrant.user_id == uuid_lib.UUID(grantee_id), UserCustomRoleGrant.custom_role_id == uuid_lib.UUID(role_id)
        ).one()
        assert str(grant.scope_entity_id) == standard["id"]
    finally:
        db.close()

    # Revoke without scope_entity_id -> 400 (must be named explicitly, mirroring project_id).
    resp = client.delete(
        f"/api/v1/orgs/{org['id']}/custom-roles/{role_id}/users/{grantee_id}", headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 400, resp.text

    resp = client.delete(
        f"/api/v1/orgs/{org['id']}/custom-roles/{role_id}/users/{grantee_id}?scope_entity_id={standard['id']}",
        headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 204, resp.text

    db = SessionLocal()
    try:
        remaining = db.query(UserCustomRoleGrant).filter(
            UserCustomRoleGrant.user_id == uuid_lib.UUID(grantee_id), UserCustomRoleGrant.custom_role_id == uuid_lib.UUID(role_id)
        ).count()
        assert remaining == 0
    finally:
        db.close()


def test_entity_scoped_custom_role_grant_delegable_via_grant_roles(client, admin_token):
    """The grant *endpoint* itself stays delegable to a `grant_roles`
    holder for an entity-scoped role too, exactly as for org-/project-scoped
    roles — `require_org_admin_or_grant_roles` gates all three identically,
    with no entity-scope-specific carve-out."""
    org, org_admin_token = create_org_admin_in(client, admin_token, "Entity Scope Delegation Org")
    standard = _create_standard(client, org_admin_token, org["id"])
    grantee_id = create_org_user(client, org_admin_token, org["id"], "delegated_standard_grantee@example.com", role="member")

    delegate_email = f"grant_roles_delegate_{uuid_lib.uuid4().hex[:8]}@example.com"
    delegate_id = create_org_user(client, org_admin_token, org["id"], delegate_email, role="member")
    grant_roles_role_resp = client.post(
        f"/api/v1/orgs/{org['id']}/custom-roles",
        json={"name": "Delegate", "description": "", "scope": "org", "permissions": ["grant_roles"]},
        headers=auth_headers(org_admin_token),
    )
    assert grant_roles_role_resp.status_code == 201, grant_roles_role_resp.text
    grant_resp = client.post(
        f"/api/v1/orgs/{org['id']}/custom-roles/{grant_roles_role_resp.json()['id']}/users/{delegate_id}",
        json={}, headers=auth_headers(org_admin_token),
    )
    assert grant_resp.status_code == 204, grant_resp.text
    delegate_token = login(client, delegate_email, "Password123!")

    role_resp = client.post(
        f"/api/v1/orgs/{org['id']}/custom-roles",
        json={"name": "Standard Delegated Role", "description": "", "scope": "standard", "permissions": []},
        headers=auth_headers(org_admin_token),
    )
    assert role_resp.status_code == 201, role_resp.text

    resp = client.post(
        f"/api/v1/orgs/{org['id']}/custom-roles/{role_resp.json()['id']}/users/{grantee_id}",
        json={"scope_entity_id": standard["id"]}, headers=auth_headers(delegate_token),
    )
    assert resp.status_code == 204, resp.text
