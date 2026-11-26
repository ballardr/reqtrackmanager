"""Tests for the Traceability & Governance module registration: its ten sub-components and their `requires` links, the
five administrative permission atoms it contributes (vocabulary, who holds each, module and custom roles) and its roles.

The atoms are a generic module extension (`ModuleDefinition.administrative_permissions`), so a duplicate of a core atom
is also pinned here against widening who holds it."""

import uuid as uuid_lib

import pytest

from app.database import SessionLocal
from app.models.module_role import UserModuleRole
from app.modules import registry as module_registry
from app.modules.registry import ModuleDefinition, build_registry, get_module, get_module_administrative_permissions
from app.modules.seams import ModuleAdministrativePermission
from app.modules.traceability._shared import (
    APPROVE_TRACEABILITY_EXCEPTIONS,
    GOVERNANCE_MANAGER_ROLE,
    GOVERNANCE_ORG_MANAGER_ROLE,
    MANAGE_ORG_GOVERNANCE,
    MANAGE_ORG_TRACEABILITY,
    MANAGE_PROJECT_GOVERNANCE,
    MANAGE_PROJECT_TRACEABILITY,
    TRACEABILITY_MANAGER_ROLE,
    TRACEABILITY_MODULE_KEY,
    TRACEABILITY_ORG_MANAGER_ROLE,
)
from app.services.permissions import ADMINISTRATIVE_PERMISSIONS, get_all_permissions, validate_permission_key
from app.services.rbac import get_effective_permissions
from tests.conftest import auth_headers, create_org_admin_in, create_org_user, create_project

ALL_ATOMS = {
    MANAGE_ORG_GOVERNANCE, MANAGE_PROJECT_GOVERNANCE, MANAGE_ORG_TRACEABILITY, MANAGE_PROJECT_TRACEABILITY,
    APPROVE_TRACEABILITY_EXCEPTIONS,
}
PROJECT_ATOMS = {MANAGE_PROJECT_GOVERNANCE, MANAGE_PROJECT_TRACEABILITY}


def _enable_module(client, token, org_id) -> None:
    resp = client.put(
        f"/api/v1/orgs/{org_id}/modules/{TRACEABILITY_MODULE_KEY}",
        json={"enabled": True, "default_project_enabled": True}, headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text


def _held(user_id: str, *, org_id: str | None = None, project_id: str | None = None) -> set[str]:
    db = SessionLocal()
    try:
        return get_effective_permissions(
            db, uuid_lib.UUID(user_id),
            organization_id=uuid_lib.UUID(org_id) if org_id else None,
            project_id=uuid_lib.UUID(project_id) if project_id else None,
        )
    finally:
        db.close()


def _set_project_role(client, token, project_id, user_id, role) -> None:
    resp = client.post(
        f"/api/v1/projects/{project_id}/roles", json={"user_id": user_id, "role": role}, headers=auth_headers(token),
    )
    assert resp.status_code in (200, 201, 204), resp.text


def _grant_module_role(user_id: str, org_id: str, role_key: str, project_id: str | None) -> None:
    db = SessionLocal()
    try:
        db.add(
            UserModuleRole(
                user_id=uuid_lib.UUID(user_id), module_key=TRACEABILITY_MODULE_KEY, role_key=role_key,
                organization_id=uuid_lib.UUID(org_id), project_id=uuid_lib.UUID(project_id) if project_id else None,
            )
        )
        db.commit()
    finally:
        db.close()


# --- registration ----------------------------------------------------------------------


def test_module_declares_ten_sub_components_with_requires():
    definition = get_module(TRACEABILITY_MODULE_KEY)
    assert definition is not None
    subs = {s.key: s for s in definition.sub_components}
    assert set(subs) == {
        "lifecycle_policies", "approval_policies", "review_policies", "baseline_policies", "governance_health",
        "requirement_types", "traceability_rules", "traceability_exceptions", "traceability_matrices",
        "cross_project_traceability",
    }
    assert subs["traceability_exceptions"].requires == ("traceability_rules",)
    assert subs["cross_project_traceability"].requires == ("traceability_rules",)
    assert all(s.default_enabled and not s.organization_only for s in subs.values())
    assert [key for key, s in subs.items() if s.requires] == ["traceability_exceptions", "cross_project_traceability"]


def test_project_nav_entry_leads_to_governance_health_and_names_its_part(client, admin_token, org_id):
    """A project sees one nav entry, the health page, tied to the `governance_health` part so the rail can hide it while that
    part is off."""
    _enable_module(client, admin_token, org_id)
    project = create_project(client, admin_token, org_id, "Governance Nav Project")
    resp = client.get(f"/api/v1/projects/{project['id']}/enabled-modules", headers=auth_headers(admin_token))
    assert resp.status_code == 200, resp.text
    manifest = {m["module_key"]: m for m in resp.json()}[TRACEABILITY_MODULE_KEY]["frontend_manifest"]
    assert manifest["nav_path"] == f"/projects/{project['id']}/modules/{TRACEABILITY_MODULE_KEY}/health"
    assert manifest["nav_label"] == "Governance Health"
    assert manifest["nav_sub_component"] == "governance_health"
    assert manifest["tier"] == "installed"


def test_module_declares_four_roles_in_two_pairs():
    definition = get_module(TRACEABILITY_MODULE_KEY)
    assert definition is not None
    roles = {r.role_key: r for r in definition.roles}
    assert {k: r.scope for k, r in roles.items()} == {
        GOVERNANCE_MANAGER_ROLE: "project", GOVERNANCE_ORG_MANAGER_ROLE: "org",
        TRACEABILITY_MANAGER_ROLE: "project", TRACEABILITY_ORG_MANAGER_ROLE: "org",
    }
    assert set(roles[GOVERNANCE_ORG_MANAGER_ROLE].permissions) == {MANAGE_ORG_GOVERNANCE, MANAGE_PROJECT_GOVERNANCE}
    assert set(roles[TRACEABILITY_ORG_MANAGER_ROLE].permissions) == {MANAGE_ORG_TRACEABILITY, MANAGE_PROJECT_TRACEABILITY}
    assert roles[GOVERNANCE_MANAGER_ROLE].permissions == (MANAGE_PROJECT_GOVERNANCE,)
    assert roles[TRACEABILITY_MANAGER_ROLE].permissions == (MANAGE_PROJECT_TRACEABILITY,)


def test_every_module_role_permission_is_a_declared_atom():
    definition = get_module(TRACEABILITY_MODULE_KEY)
    assert definition is not None
    declared = {a.key for a in definition.administrative_permissions}
    assert declared == ALL_ATOMS
    for role in definition.roles:
        assert set(role.permissions) <= declared


def test_module_default_is_off_until_an_organisation_opts_in():
    definition = get_module(TRACEABILITY_MODULE_KEY)
    assert definition is not None
    assert definition.default_enabled is False


# --- permission vocabulary -------------------------------------------------------------


def test_atoms_are_in_the_permission_vocabulary_and_valid_for_custom_roles(client, admin_token, org_id):
    db = SessionLocal()
    try:
        keys = {p.key for p in get_all_permissions(db, uuid_lib.UUID(org_id))}
        assert ALL_ATOMS <= keys
        for atom in ALL_ATOMS:
            validate_permission_key(db, uuid_lib.UUID(org_id), atom)
    finally:
        db.close()
    # No atom shadows a core one.
    assert ALL_ATOMS.isdisjoint(ADMINISTRATIVE_PERMISSIONS)


# --- who holds each atom ---------------------------------------------------------------


def test_org_admin_holds_every_atom_in_org_and_project_scope(client, admin_token):
    org, token = create_org_admin_in(client, admin_token, "Traceability Org Admin Atoms Org")
    project = create_project(client, token, org["id"])
    me = client.get("/api/v1/auth/me", headers=auth_headers(token)).json()["id"]
    assert ALL_ATOMS <= _held(me, org_id=org["id"])
    assert ALL_ATOMS <= _held(me, project_id=project["id"])


def test_project_roles_hold_only_their_project_atoms(client, admin_token):
    org, token = create_org_admin_in(client, admin_token, "Traceability Project Role Atoms Org")
    project = create_project(client, token, org["id"])
    manager = create_org_user(client, token, org["id"], "tr_manager@example.com")
    administrator = create_org_user(client, token, org["id"], "tr_administrator@example.com")
    member = create_org_user(client, token, org["id"], "tr_member@example.com")
    _set_project_role(client, token, project["id"], manager, "project_manager")
    _set_project_role(client, token, project["id"], administrator, "project_administrator")
    _set_project_role(client, token, project["id"], member, "member")

    manager_held = _held(manager, project_id=project["id"])
    assert PROJECT_ATOMS | {APPROVE_TRACEABILITY_EXCEPTIONS} <= manager_held
    assert not manager_held & {MANAGE_ORG_GOVERNANCE, MANAGE_ORG_TRACEABILITY}

    administrator_held = _held(administrator, project_id=project["id"])
    assert PROJECT_ATOMS <= administrator_held
    assert APPROVE_TRACEABILITY_EXCEPTIONS not in administrator_held
    assert not administrator_held & {MANAGE_ORG_GOVERNANCE, MANAGE_ORG_TRACEABILITY}

    assert not _held(member, project_id=project["id"]) & ALL_ATOMS
    # A project role grants nothing at organisation scope.
    assert not _held(manager, org_id=org["id"]) & ALL_ATOMS


@pytest.mark.parametrize(
    ("role_key", "scope", "expected"),
    [
        (GOVERNANCE_MANAGER_ROLE, "project", {MANAGE_PROJECT_GOVERNANCE}),
        (TRACEABILITY_MANAGER_ROLE, "project", {MANAGE_PROJECT_TRACEABILITY}),
        (GOVERNANCE_ORG_MANAGER_ROLE, "org", {MANAGE_ORG_GOVERNANCE, MANAGE_PROJECT_GOVERNANCE}),
        (TRACEABILITY_ORG_MANAGER_ROLE, "org", {MANAGE_ORG_TRACEABILITY, MANAGE_PROJECT_TRACEABILITY}),
    ],
)
def test_module_role_grants_its_atoms_only_while_the_module_is_enabled(
    client, admin_token, role_key, scope, expected,
):
    org, token = create_org_admin_in(client, admin_token, f"Traceability Role {role_key} Org")
    project = create_project(client, token, org["id"])
    grantee = create_org_user(client, token, org["id"], f"{role_key}@example.com")
    _grant_module_role(grantee, org["id"], role_key, project["id"] if scope == "project" else None)

    # The module is off for the organisation, so the role grants nothing.
    assert not _held(grantee, project_id=project["id"]) & ALL_ATOMS

    _enable_module(client, token, org["id"])
    other_project = create_project(client, token, org["id"], "Second Project")
    held = _held(grantee, project_id=project["id"]) & ALL_ATOMS
    assert held == expected
    # A project-scoped grant does not reach another project; an organisation grant reaches every project.
    held_elsewhere = _held(grantee, project_id=other_project["id"]) & ALL_ATOMS
    assert held_elsewhere == (set() if scope == "project" else expected)


# --- registry guard ---------------------------------------------------------------------


def test_a_module_cannot_claim_a_core_or_earlier_atom():
    colliding = ModuleDefinition(
        key="fake_atom_collision_module", name="Fake", description="Fixture.", version="0.0.1", default_enabled=True,
        implemented=False, get_router=lambda: None,
        administrative_permissions=(
            ModuleAdministrativePermission(key="grant_roles", label="Grant roles"),
            ModuleAdministrativePermission(key=MANAGE_ORG_GOVERNANCE, label="Duplicate"),
            ModuleAdministrativePermission(key="fake_only_atom", label="Fake only"),
        ),
    )
    module_registry.INSTALLED_MODULES.append(colliding)
    build_registry(force=True)
    try:
        owners = {atom.key: key for key, atom in get_module_administrative_permissions()}
        assert "grant_roles" not in owners
        assert owners[MANAGE_ORG_GOVERNANCE] == TRACEABILITY_MODULE_KEY
        assert owners["fake_only_atom"] == "fake_atom_collision_module"
    finally:
        module_registry.INSTALLED_MODULES[:] = [m for m in module_registry.INSTALLED_MODULES if m is not colliding]
        build_registry(force=True)


@pytest.mark.parametrize("key", ["Manage", "manage-it", "1manage", "manage:it", ""])
def test_an_atom_key_must_be_a_bare_lower_case_key(key):
    with pytest.raises(ValueError, match="lower-case"):
        ModuleAdministrativePermission(key=key, label="Bad")
