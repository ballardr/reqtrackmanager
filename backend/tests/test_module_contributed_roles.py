"""Tests for the module system's Phase 2 module-contributed RBAC
(docs/compliance-module-plan.md): `ModuleRoleDefinition`/`user_module_roles`
grant-and-revoke idempotency (both org- and project-scoped), `services.rbac.
require_module_role`'s admin-override composition at each scope, the
404-not-403 behaviour when a role's module is disabled/non-entitled, the
enabled-modules-only filtering `list_org_users`/`GET .../effective-members`/
the two "available module roles" read endpoints all apply, the 400
validation on `POST .../module-roles`, and `sync_module_role_definitions`'s
own upsert-never-delete behaviour.

This is a separate file from `test_module_system_rbac.py` (Phase 0's
server-tier RBAC tests) rather than an extension of it — same reasoning
Phase 0's own notes give for why it isn't folded into `test_access_review.py`:
this is a genuinely different module-system concern (module-contributed
roles, not server-tier roles), even though both files register a fixture
module into the same `INSTALLED_MODULES` list.

Since no real module is registered in `INSTALLED_MODULES` yet (Compliance
doesn't land until Phase 5), every test here uses the `fake_module` fixture
below, which mirrors `test_module_registry.py`'s own fixture mechanics
exactly (mutate `INSTALLED_MODULES` in place, rebuild the registry cache,
always tear down) — see that fixture's own comment for why reassigning the
list wouldn't work."""

import uuid as uuid_lib
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.database import SessionLocal
from app.models.audit import AuditEvent
from app.models.module import OrganizationModuleEnablement
from app.models.module_role import ModuleRoleDefinitionRow, UserModuleRole
from app.models.user import User
from app.modules import registry as module_registry
from app.modules.registry import ModuleDefinition, ModuleRoleDefinition, build_registry, sync_module_role_definitions
from app.services.rbac import require_module_role
from tests.conftest import auth_headers, create_org_user, create_project, login

FAKE_MODULE_KEY = "fake_role_test_module"
ORG_ROLE_KEY = "test_org_role"
PROJECT_ROLE_KEY = "test_project_role"


class _FakeRequest:
    """Minimal stand-in for FastAPI's `Request`, same as `test_module_
    registry.py`'s own — just enough for `check_pat_scope`/`check_pat_
    project_scope`'s `getattr(request.state, ..., None)` reads to behave
    like an ordinary (non-PAT) session request."""

    def __init__(self):
        self.state = SimpleNamespace()


def _fake_module(**overrides) -> ModuleDefinition:
    defaults = dict(
        key=FAKE_MODULE_KEY, name="Fake Role Test Module",
        description="A fixture module registered only for this test file's own assertions.",
        version="0.0.1", default_enabled=True, implemented=False, get_router=lambda: None,
        roles=(
            ModuleRoleDefinition(
                role_key=ORG_ROLE_KEY, name="Test Org Role",
                description="An org-scoped fixture role.", scope="org",
            ),
            ModuleRoleDefinition(
                role_key=PROJECT_ROLE_KEY, name="Test Project Role",
                description="A project-scoped fixture role.", scope="project",
            ),
        ),
    )
    defaults.update(overrides)
    return ModuleDefinition(**defaults)


@pytest.fixture
def fake_module():
    """Registers a fake module (with one org-scoped and one project-scoped
    role) into `INSTALLED_MODULES` for the duration of one test, rebuilding
    the registry cache before and after so the change (and its later
    removal) actually takes effect — mirrors `test_module_registry.py`'s
    own `fake_module` fixture. Also syncs `module_role_definitions` so rows
    exist for it, per this phase's own spec."""
    module_registry.INSTALLED_MODULES.append(_fake_module())
    build_registry(force=True)
    db = SessionLocal()
    try:
        sync_module_role_definitions(db)
    finally:
        db.close()
    yield FAKE_MODULE_KEY
    module_registry.INSTALLED_MODULES[:] = [
        m for m in module_registry.INSTALLED_MODULES if m.key != FAKE_MODULE_KEY
    ]
    build_registry(force=True)


def _get_admin_user(db) -> User:
    return db.query(User).filter(User.email == "admin@example.com").first()


def _disable_module(db, organization_id, module_key: str) -> None:
    db.add(OrganizationModuleEnablement(organization_id=organization_id, module_key=module_key, enabled=False))
    db.commit()


def _enable_module(db, organization_id, module_key: str) -> None:
    row = db.query(OrganizationModuleEnablement).filter(
        OrganizationModuleEnablement.organization_id == organization_id,
        OrganizationModuleEnablement.module_key == module_key,
    ).first()
    if row is not None:
        db.delete(row)
        db.commit()


# --- Grant/revoke idempotency ------------------------------------------------


def test_org_module_role_grant_and_revoke_idempotent(client, admin_token, org_id, fake_module):
    user_id = create_org_user(client, admin_token, org_id, "org_role_grantee@example.com", role="member")

    resp = client.post(
        f"/api/v1/orgs/{org_id}/users/{user_id}/module-roles",
        json={"module_key": fake_module, "role_key": ORG_ROLE_KEY}, headers=auth_headers(admin_token),
    )
    assert resp.status_code == 204, resp.text
    # Second grant of the same role is a silent no-op, not a 409/500.
    resp = client.post(
        f"/api/v1/orgs/{org_id}/users/{user_id}/module-roles",
        json={"module_key": fake_module, "role_key": ORG_ROLE_KEY}, headers=auth_headers(admin_token),
    )
    assert resp.status_code == 204, resp.text

    resp = client.get(f"/api/v1/orgs/{org_id}/users", headers=auth_headers(admin_token))
    by_id = {u["user_id"]: u for u in resp.json()}
    assert by_id[user_id]["module_roles"] == [{"module_key": fake_module, "role_key": ORG_ROLE_KEY}]

    resp = client.delete(
        f"/api/v1/orgs/{org_id}/users/{user_id}/module-roles/{fake_module}/{ORG_ROLE_KEY}",
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 204
    # Revoking an ungranted role is also a no-op.
    resp = client.delete(
        f"/api/v1/orgs/{org_id}/users/{user_id}/module-roles/{fake_module}/{ORG_ROLE_KEY}",
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 204

    resp = client.get(f"/api/v1/orgs/{org_id}/users", headers=auth_headers(admin_token))
    by_id = {u["user_id"]: u for u in resp.json()}
    assert by_id[user_id]["module_roles"] == []


def test_project_module_role_grant_and_revoke_idempotent(client, admin_token, org_id, fake_module):
    project = create_project(client, admin_token, org_id, "Module Role Grant Project")
    user_id = create_org_user(client, admin_token, org_id, "project_role_grantee@example.com", role="member")
    client.post(f"/api/v1/projects/{project['id']}/roles", json={"user_id": user_id, "role": "member"},
                headers=auth_headers(admin_token))

    resp = client.post(
        f"/api/v1/projects/{project['id']}/members/{user_id}/module-roles",
        json={"module_key": fake_module, "role_key": PROJECT_ROLE_KEY}, headers=auth_headers(admin_token),
    )
    assert resp.status_code == 204, resp.text
    resp = client.post(
        f"/api/v1/projects/{project['id']}/members/{user_id}/module-roles",
        json={"module_key": fake_module, "role_key": PROJECT_ROLE_KEY}, headers=auth_headers(admin_token),
    )
    assert resp.status_code == 204, resp.text

    resp = client.get(f"/api/v1/projects/{project['id']}/effective-members", headers=auth_headers(admin_token))
    by_id = {m["user_id"]: m for m in resp.json()}
    assert by_id[user_id]["module_roles"] == [{"module_key": fake_module, "role_key": PROJECT_ROLE_KEY}]

    resp = client.delete(
        f"/api/v1/projects/{project['id']}/members/{user_id}/module-roles/{fake_module}/{PROJECT_ROLE_KEY}",
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 204
    resp = client.delete(
        f"/api/v1/projects/{project['id']}/members/{user_id}/module-roles/{fake_module}/{PROJECT_ROLE_KEY}",
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 204

    resp = client.get(f"/api/v1/projects/{project['id']}/effective-members", headers=auth_headers(admin_token))
    by_id = {m["user_id"]: m for m in resp.json()}
    assert by_id[user_id]["module_roles"] == []


def test_org_module_role_grant_is_audit_logged(client, admin_token, org_id, fake_module):
    user_id = create_org_user(client, admin_token, org_id, "org_role_audit@example.com", role="member")
    resp = client.post(
        f"/api/v1/orgs/{org_id}/users/{user_id}/module-roles",
        json={"module_key": fake_module, "role_key": ORG_ROLE_KEY}, headers=auth_headers(admin_token),
    )
    assert resp.status_code == 204
    db = SessionLocal()
    try:
        event = db.query(AuditEvent).filter(
            AuditEvent.entity_type == "user_module_role", AuditEvent.action == "granted"
        ).first()
        assert event is not None
        assert event.detail["module_key"] == fake_module
        assert event.detail["role_key"] == ORG_ROLE_KEY
    finally:
        db.close()


# --- require_module_role composition ----------------------------------------


def test_require_module_role_org_scope_composition(client, admin_token, org_id, fake_module):
    db = SessionLocal()
    try:
        dependency = require_module_role(fake_module, ORG_ROLE_KEY)
        org_uuid = uuid_lib.UUID(org_id)

        # A genuine server admin passes with zero grants.
        admin_user = _get_admin_user(db)
        result = dependency(organization_id=org_uuid, request=_FakeRequest(), current_user=admin_user, db=db)
        assert result.id == admin_user.id

        # A plain member with none of the qualifying conditions is refused.
        plain_id = create_org_user(client, admin_token, org_id, "plain_org_scope@example.com", role="member")
        plain_user = db.get(User, uuid_lib.UUID(plain_id))
        with pytest.raises(HTTPException) as exc_info:
            dependency(organization_id=org_uuid, request=_FakeRequest(), current_user=plain_user, db=db)
        assert exc_info.value.status_code == 403

        # An org admin (zero grants of their own) passes via the ORG_ADMIN override.
        org_admin_id = create_org_user(client, admin_token, org_id, "org_admin_scope@example.com", role="org_admin")
        org_admin_user = db.get(User, uuid_lib.UUID(org_admin_id))
        result = dependency(organization_id=org_uuid, request=_FakeRequest(), current_user=org_admin_user, db=db)
        assert result.id == org_admin_user.id

        # A user holding only the specific UserModuleRole grant passes.
        db.add(
            UserModuleRole(
                user_id=uuid_lib.UUID(plain_id), module_key=fake_module, role_key=ORG_ROLE_KEY,
                organization_id=org_uuid,
            )
        )
        db.commit()
        result = dependency(organization_id=org_uuid, request=_FakeRequest(), current_user=plain_user, db=db)
        assert result.id == plain_user.id
    finally:
        db.close()


def test_require_module_role_project_scope_composition(client, admin_token, org_id, fake_module):
    project = create_project(client, admin_token, org_id, "Module Role Composition Project")
    project_uuid = uuid_lib.UUID(project["id"])
    db = SessionLocal()
    try:
        dependency = require_module_role(fake_module, PROJECT_ROLE_KEY)

        # A genuine server admin passes with zero grants.
        admin_user = _get_admin_user(db)
        result = dependency(project_id=project_uuid, request=_FakeRequest(), current_user=admin_user, db=db)
        assert result.id == admin_user.id

        # A plain project member with none of the qualifying conditions is refused.
        plain_id = create_org_user(client, admin_token, org_id, "plain_project_scope@example.com", role="member")
        client.post(f"/api/v1/projects/{project['id']}/roles", json={"user_id": plain_id, "role": "member"},
                    headers=auth_headers(admin_token))
        plain_user = db.get(User, uuid_lib.UUID(plain_id))
        with pytest.raises(HTTPException) as exc_info:
            dependency(project_id=project_uuid, request=_FakeRequest(), current_user=plain_user, db=db)
        assert exc_info.value.status_code == 403

        # A project manager (zero grants of their own) passes via the PROJECT_MANAGER override.
        manager_id = create_org_user(client, admin_token, org_id, "project_manager_scope@example.com", role="member")
        client.post(f"/api/v1/projects/{project['id']}/roles",
                    json={"user_id": manager_id, "role": "project_manager"}, headers=auth_headers(admin_token))
        manager_user = db.get(User, uuid_lib.UUID(manager_id))
        result = dependency(project_id=project_uuid, request=_FakeRequest(), current_user=manager_user, db=db)
        assert result.id == manager_user.id

        # A user holding only the specific UserModuleRole grant passes.
        db.add(
            UserModuleRole(
                user_id=uuid_lib.UUID(plain_id), module_key=fake_module, role_key=PROJECT_ROLE_KEY,
                organization_id=uuid_lib.UUID(org_id), project_id=project_uuid,
            )
        )
        db.commit()
        result = dependency(project_id=project_uuid, request=_FakeRequest(), current_user=plain_user, db=db)
        assert result.id == plain_user.id
    finally:
        db.close()


def test_require_module_role_404_when_module_disabled_even_for_admins(client, admin_token, org_id, fake_module):
    db = SessionLocal()
    try:
        org_uuid = uuid_lib.UUID(org_id)
        _disable_module(db, org_uuid, fake_module)
        dependency = require_module_role(fake_module, ORG_ROLE_KEY)
        admin_user = _get_admin_user(db)
        with pytest.raises(HTTPException) as exc_info:
            dependency(organization_id=org_uuid, request=_FakeRequest(), current_user=admin_user, db=db)
        assert exc_info.value.status_code == 404

        org_admin_id = create_org_user(client, admin_token, org_id, "org_admin_disabled@example.com", role="org_admin")
        org_admin_user = db.get(User, uuid_lib.UUID(org_admin_id))
        with pytest.raises(HTTPException) as exc_info:
            dependency(organization_id=org_uuid, request=_FakeRequest(), current_user=org_admin_user, db=db)
        assert exc_info.value.status_code == 404
    finally:
        _enable_module(db, uuid_lib.UUID(org_id), fake_module)
        db.close()


def test_require_module_role_unknown_module_or_role_raises_value_error_at_construction():
    with pytest.raises(ValueError):
        require_module_role("no_such_module_key", "whatever")
    with pytest.raises(ValueError):
        require_module_role(FAKE_MODULE_KEY, "no_such_role_key")


# --- Enabled-modules-only filtering ------------------------------------------


def test_disabled_module_role_excluded_from_listings_but_grant_persists(client, admin_token, org_id, fake_module):
    user_id = create_org_user(client, admin_token, org_id, "disabled_module_grantee@example.com", role="member")
    resp = client.post(
        f"/api/v1/orgs/{org_id}/users/{user_id}/module-roles",
        json={"module_key": fake_module, "role_key": ORG_ROLE_KEY}, headers=auth_headers(admin_token),
    )
    assert resp.status_code == 204

    resp = client.get(f"/api/v1/orgs/{org_id}/module-roles", headers=auth_headers(admin_token))
    assert any(r["module_key"] == fake_module and r["role_key"] == ORG_ROLE_KEY for r in resp.json())
    resp = client.get(f"/api/v1/orgs/{org_id}/users", headers=auth_headers(admin_token))
    by_id = {u["user_id"]: u for u in resp.json()}
    assert by_id[user_id]["module_roles"] == [{"module_key": fake_module, "role_key": ORG_ROLE_KEY}]

    db = SessionLocal()
    try:
        _disable_module(db, uuid_lib.UUID(org_id), fake_module)
    finally:
        db.close()

    resp = client.get(f"/api/v1/orgs/{org_id}/module-roles", headers=auth_headers(admin_token))
    assert not any(r["module_key"] == fake_module for r in resp.json())
    resp = client.get(f"/api/v1/orgs/{org_id}/users", headers=auth_headers(admin_token))
    by_id = {u["user_id"]: u for u in resp.json()}
    assert by_id[user_id]["module_roles"] == []

    # The underlying grant row still exists — this is a filter, not a deletion.
    db = SessionLocal()
    try:
        row = db.query(UserModuleRole).filter(
            UserModuleRole.user_id == uuid_lib.UUID(user_id), UserModuleRole.module_key == fake_module,
            UserModuleRole.role_key == ORG_ROLE_KEY,
        ).first()
        assert row is not None
        _enable_module(db, uuid_lib.UUID(org_id), fake_module)
    finally:
        db.close()

    resp = client.get(f"/api/v1/orgs/{org_id}/module-roles", headers=auth_headers(admin_token))
    assert any(r["module_key"] == fake_module and r["role_key"] == ORG_ROLE_KEY for r in resp.json())
    resp = client.get(f"/api/v1/orgs/{org_id}/users", headers=auth_headers(admin_token))
    by_id = {u["user_id"]: u for u in resp.json()}
    assert by_id[user_id]["module_roles"] == [{"module_key": fake_module, "role_key": ORG_ROLE_KEY}]


# --- 400 validation on grant --------------------------------------------------


def test_assign_org_module_role_400_for_unknown_role_key(client, admin_token, org_id, fake_module):
    user_id = create_org_user(client, admin_token, org_id, "bad_role_key@example.com", role="member")
    resp = client.post(
        f"/api/v1/orgs/{org_id}/users/{user_id}/module-roles",
        json={"module_key": fake_module, "role_key": "not_a_real_role"}, headers=auth_headers(admin_token),
    )
    assert resp.status_code == 400


def test_assign_org_module_role_400_for_wrong_scope(client, admin_token, org_id, fake_module):
    """Posting the project-scoped role to the org endpoint must 400 —
    scope mismatch is treated the same as a nonexistent role."""
    user_id = create_org_user(client, admin_token, org_id, "wrong_scope@example.com", role="member")
    resp = client.post(
        f"/api/v1/orgs/{org_id}/users/{user_id}/module-roles",
        json={"module_key": fake_module, "role_key": PROJECT_ROLE_KEY}, headers=auth_headers(admin_token),
    )
    assert resp.status_code == 400


def test_assign_project_module_role_400_for_wrong_scope(client, admin_token, org_id, fake_module):
    """Posting the org-scoped role to the project endpoint must also 400."""
    project = create_project(client, admin_token, org_id, "Wrong Scope Project")
    user_id = create_org_user(client, admin_token, org_id, "wrong_scope_project@example.com", role="member")
    client.post(f"/api/v1/projects/{project['id']}/roles", json={"user_id": user_id, "role": "member"},
                headers=auth_headers(admin_token))
    resp = client.post(
        f"/api/v1/projects/{project['id']}/members/{user_id}/module-roles",
        json={"module_key": fake_module, "role_key": ORG_ROLE_KEY}, headers=auth_headers(admin_token),
    )
    assert resp.status_code == 400


def test_assign_org_module_role_400_when_module_disabled(client, admin_token, org_id, fake_module):
    db = SessionLocal()
    try:
        _disable_module(db, uuid_lib.UUID(org_id), fake_module)
    finally:
        db.close()
    user_id = create_org_user(client, admin_token, org_id, "disabled_grant_attempt@example.com", role="member")
    resp = client.post(
        f"/api/v1/orgs/{org_id}/users/{user_id}/module-roles",
        json={"module_key": fake_module, "role_key": ORG_ROLE_KEY}, headers=auth_headers(admin_token),
    )
    assert resp.status_code == 400
    db = SessionLocal()
    try:
        _enable_module(db, uuid_lib.UUID(org_id), fake_module)
    finally:
        db.close()


def test_org_module_roles_endpoint_403_for_non_admin_grant(client, admin_token, org_id, fake_module):
    """`POST`/`DELETE .../module-roles` require `ORG_ADMIN`, same as
    `assign_org_role`/`revoke_org_role` — a plain member can read the
    option list (`GET .../module-roles`) but not grant/revoke."""
    user_id = create_org_user(client, admin_token, org_id, "cannot_grant@example.com", role="member")
    token = login(client, "cannot_grant@example.com", "Password123!")
    resp = client.get(f"/api/v1/orgs/{org_id}/module-roles", headers=auth_headers(token))
    assert resp.status_code == 200
    resp = client.post(
        f"/api/v1/orgs/{org_id}/users/{user_id}/module-roles",
        json={"module_key": fake_module, "role_key": ORG_ROLE_KEY}, headers=auth_headers(token),
    )
    assert resp.status_code == 403


# --- sync_module_role_definitions --------------------------------------------


def test_sync_module_role_definitions_upserts_without_duplicating(fake_module):
    db = SessionLocal()
    try:
        rows = db.query(ModuleRoleDefinitionRow).filter(ModuleRoleDefinitionRow.module_key == fake_module).all()
        assert len(rows) == 2
        row = next(r for r in rows if r.role_key == ORG_ROLE_KEY)
        assert row.name == "Test Org Role"

        # Update the live registry's definition (new name/description),
        # then sync again — the existing row must be updated in place, not
        # duplicated.
        module_registry.INSTALLED_MODULES[:] = [
            m for m in module_registry.INSTALLED_MODULES if m.key != FAKE_MODULE_KEY
        ]
        module_registry.INSTALLED_MODULES.append(
            _fake_module(
                roles=(
                    ModuleRoleDefinition(
                        role_key=ORG_ROLE_KEY, name="Renamed Org Role",
                        description="An updated description.", scope="org",
                    ),
                    ModuleRoleDefinition(
                        role_key=PROJECT_ROLE_KEY, name="Test Project Role",
                        description="A project-scoped fixture role.", scope="project",
                    ),
                )
            )
        )
        build_registry(force=True)
        sync_module_role_definitions(db)

        rows = db.query(ModuleRoleDefinitionRow).filter(ModuleRoleDefinitionRow.module_key == fake_module).all()
        assert len(rows) == 2
        row = next(r for r in rows if r.role_key == ORG_ROLE_KEY)
        assert row.name == "Renamed Org Role"
        assert row.description == "An updated description."
    finally:
        db.close()


def test_sync_module_role_definitions_never_deletes_a_row_for_a_removed_module(fake_module):
    db = SessionLocal()
    try:
        rows = db.query(ModuleRoleDefinitionRow).filter(ModuleRoleDefinitionRow.module_key == fake_module).all()
        assert len(rows) == 2

        # Remove the fake module from the registry entirely and re-sync —
        # the previously-synced rows must still exist (append-only mirror).
        module_registry.INSTALLED_MODULES[:] = [
            m for m in module_registry.INSTALLED_MODULES if m.key != FAKE_MODULE_KEY
        ]
        build_registry(force=True)
        sync_module_role_definitions(db)

        rows = db.query(ModuleRoleDefinitionRow).filter(ModuleRoleDefinitionRow.module_key == fake_module).all()
        assert len(rows) == 2
    finally:
        # Restore for the fixture's own teardown (which removes-by-key and
        # rebuilds — harmless no-op if already absent, but keeps this test
        # from leaving the registry in a state the fixture teardown doesn't
        # expect).
        if not any(m.key == FAKE_MODULE_KEY for m in module_registry.INSTALLED_MODULES):
            module_registry.INSTALLED_MODULES.append(_fake_module())
            build_registry(force=True)
        db.close()
