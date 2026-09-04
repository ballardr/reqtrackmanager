"""Tests for the module system's Phase 1 two-tier gating and backend
plugin-loading infrastructure (docs/compliance-module-plan.md): effective
entitlement/enablement resolution (`app.modules.registry.
is_module_entitled`/`is_module_enabled`), the `require_org_module_enabled`/
`require_project_module_enabled` RBAC dependencies' 404-not-403 behaviour,
`build_registry`'s three-source merge logic and its `ALLOW_EXTERNAL_MODULES`
gating, and the org-tier (`/orgs/{id}/modules`) and server-tier
(`/system/modules`, `/system/orgs/{id}/module-entitlements`) admin
endpoints.

Every test that registers a fixture module into the process-global
`INSTALLED_MODULES` list uses the `fake_module` fixture below, which always
tears down by removing it and rebuilding the registry cache
(`build_registry(force=True)`) — this repo's standing rule that tests must
not depend on execution order applies just as much to this module-level
mutable list as it does to database rows."""

import uuid as uuid_lib
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.config import get_settings
from app.database import SessionLocal
from app.models.audit import AuditEvent
from app.models.module import OrganizationModuleEnablement, OrganizationModuleEntitlement
from app.models.user import User
from app.modules import registry as module_registry
from app.modules.registry import ModuleDefinition, build_registry
from app.services.rbac import require_org_module_enabled, require_project_module_enabled
from tests.conftest import auth_headers, create_org_admin_in, create_org_user, create_project, login

FAKE_MODULE_KEY = "fake_test_module"


class _FakeRequest:
    """Minimal stand-in for FastAPI's `Request` — just enough for
    `check_pat_scope`/`check_pat_project_scope`'s `getattr(request.state,
    ..., None)` reads to behave like an ordinary (non-PAT) session
    request, so the RBAC dependencies under test can be called directly
    without going through the full FastAPI DI/HTTP stack."""

    def __init__(self):
        self.state = SimpleNamespace()


def _fake_module(**overrides) -> ModuleDefinition:
    defaults = dict(
        key=FAKE_MODULE_KEY, name="Fake Test Module",
        description="A fixture module registered only for this test file's own assertions.",
        version="0.0.1", default_enabled=True, implemented=False, get_router=lambda: None,
    )
    defaults.update(overrides)
    return ModuleDefinition(**defaults)


@pytest.fixture
def fake_module():
    """Registers a fake module into `INSTALLED_MODULES` for the duration
    of one test, rebuilding the registry cache before and after so the
    change (and its later removal) actually takes effect."""
    module_registry.INSTALLED_MODULES.append(_fake_module())
    build_registry(force=True)
    yield FAKE_MODULE_KEY
    module_registry.INSTALLED_MODULES[:] = [
        m for m in module_registry.INSTALLED_MODULES if m.key != FAKE_MODULE_KEY
    ]
    build_registry(force=True)


def _get_admin_user(db) -> User:
    return db.query(User).filter(User.email == "admin@example.com").first()


# --- Effective entitlement/enablement resolution ----------------------------


def test_effective_entitlement_and_enablement_all_four_combinations(client, admin_token, org_id, fake_module):
    db = SessionLocal()
    try:
        org_uuid = uuid_lib.UUID(org_id)

        # (a) entitled (default policy is OPEN, no override row) + enabled
        # (registry default_enabled=True, no override row).
        assert module_registry.is_module_entitled(db, org_uuid, fake_module) is True
        assert module_registry.is_module_enabled(db, org_uuid, fake_module) is True

        # (b) entitled + explicitly disabled via an OrganizationModuleEnablement row.
        enablement = OrganizationModuleEnablement(organization_id=org_uuid, module_key=fake_module, enabled=False)
        db.add(enablement)
        db.commit()
        assert module_registry.is_module_entitled(db, org_uuid, fake_module) is True
        assert module_registry.is_module_enabled(db, org_uuid, fake_module) is False

        # (c) not entitled, but an enablement row says enabled=True — the AND
        # logic must still yield an effective False.
        db.delete(enablement)
        db.commit()
        db.add(OrganizationModuleEntitlement(organization_id=org_uuid, module_key=fake_module, entitled=False))
        db.add(OrganizationModuleEnablement(organization_id=org_uuid, module_key=fake_module, enabled=True))
        db.commit()
        assert module_registry.is_module_entitled(db, org_uuid, fake_module) is False
        assert module_registry.is_module_enabled(db, org_uuid, fake_module) is False

        # (d) not entitled, no enablement row either.
        db.query(OrganizationModuleEnablement).filter(
            OrganizationModuleEnablement.organization_id == org_uuid,
            OrganizationModuleEnablement.module_key == fake_module,
        ).delete()
        db.commit()
        assert module_registry.is_module_entitled(db, org_uuid, fake_module) is False
        assert module_registry.is_module_enabled(db, org_uuid, fake_module) is False
    finally:
        db.close()


def test_org_modules_endpoint_reflects_computed_entitlement_and_enablement(client, admin_token, org_id, fake_module):
    resp = client.get(f"/api/v1/orgs/{org_id}/modules", headers=auth_headers(admin_token))
    assert resp.status_code == 200
    by_key = {m["module_key"]: m for m in resp.json()}
    assert by_key[fake_module]["entitled"] is True
    assert by_key[fake_module]["enabled"] is True
    assert by_key[fake_module]["default_enabled"] is True
    assert by_key[fake_module]["implemented"] is False

    db = SessionLocal()
    try:
        db.add(
            OrganizationModuleEntitlement(
                organization_id=uuid_lib.UUID(org_id), module_key=fake_module, entitled=False
            )
        )
        db.commit()
    finally:
        db.close()

    resp = client.get(f"/api/v1/orgs/{org_id}/modules", headers=auth_headers(admin_token))
    by_key = {m["module_key"]: m for m in resp.json()}
    # Non-entitled modules are included, not filtered out (greyed out client-side).
    assert by_key[fake_module]["entitled"] is False
    assert by_key[fake_module]["enabled"] is False


# --- require_org_module_enabled / require_project_module_enabled -----------


def test_require_org_module_enabled_404_for_unregistered_module(client, admin_token, org_id):
    db = SessionLocal()
    try:
        admin_user = _get_admin_user(db)
        dependency = require_org_module_enabled("this_module_key_is_not_registered_anywhere")
        with pytest.raises(HTTPException) as exc_info:
            dependency(organization_id=uuid_lib.UUID(org_id), request=_FakeRequest(), current_user=admin_user, db=db)
        assert exc_info.value.status_code == 404
    finally:
        db.close()


def test_require_org_module_enabled_404_when_disabled(client, admin_token, org_id, fake_module):
    db = SessionLocal()
    try:
        org_uuid = uuid_lib.UUID(org_id)
        db.add(OrganizationModuleEnablement(organization_id=org_uuid, module_key=fake_module, enabled=False))
        db.commit()
        admin_user = _get_admin_user(db)
        dependency = require_org_module_enabled(fake_module)
        with pytest.raises(HTTPException) as exc_info:
            dependency(organization_id=org_uuid, request=_FakeRequest(), current_user=admin_user, db=db)
        assert exc_info.value.status_code == 404
    finally:
        db.close()


def test_require_org_module_enabled_404_when_not_entitled(client, admin_token, org_id, fake_module):
    db = SessionLocal()
    try:
        org_uuid = uuid_lib.UUID(org_id)
        db.add(OrganizationModuleEntitlement(organization_id=org_uuid, module_key=fake_module, entitled=False))
        db.commit()
        admin_user = _get_admin_user(db)
        dependency = require_org_module_enabled(fake_module)
        with pytest.raises(HTTPException) as exc_info:
            dependency(organization_id=org_uuid, request=_FakeRequest(), current_user=admin_user, db=db)
        assert exc_info.value.status_code == 404
    finally:
        db.close()


def test_require_org_module_enabled_passes_when_effectively_enabled(client, admin_token, org_id, fake_module):
    db = SessionLocal()
    try:
        admin_user = _get_admin_user(db)
        dependency = require_org_module_enabled(fake_module)
        result = dependency(
            organization_id=uuid_lib.UUID(org_id), request=_FakeRequest(), current_user=admin_user, db=db
        )
        assert result.id == admin_user.id
    finally:
        db.close()


def test_require_project_module_enabled_404_when_disabled(client, admin_token, org_id, fake_module):
    project = create_project(client, admin_token, org_id, "Module Gating Project Disabled")
    db = SessionLocal()
    try:
        org_uuid = uuid_lib.UUID(org_id)
        db.add(OrganizationModuleEnablement(organization_id=org_uuid, module_key=fake_module, enabled=False))
        db.commit()
        admin_user = _get_admin_user(db)
        dependency = require_project_module_enabled(fake_module)
        with pytest.raises(HTTPException) as exc_info:
            dependency(
                project_id=uuid_lib.UUID(project["id"]), request=_FakeRequest(), current_user=admin_user, db=db
            )
        assert exc_info.value.status_code == 404
    finally:
        db.close()


def test_require_project_module_enabled_404_when_not_entitled(client, admin_token, org_id, fake_module):
    project = create_project(client, admin_token, org_id, "Module Gating Project Not Entitled")
    db = SessionLocal()
    try:
        org_uuid = uuid_lib.UUID(org_id)
        db.add(OrganizationModuleEntitlement(organization_id=org_uuid, module_key=fake_module, entitled=False))
        db.commit()
        admin_user = _get_admin_user(db)
        dependency = require_project_module_enabled(fake_module)
        with pytest.raises(HTTPException) as exc_info:
            dependency(
                project_id=uuid_lib.UUID(project["id"]), request=_FakeRequest(), current_user=admin_user, db=db
            )
        assert exc_info.value.status_code == 404
    finally:
        db.close()


def test_require_project_module_enabled_passes_when_effectively_enabled(client, admin_token, org_id, fake_module):
    project = create_project(client, admin_token, org_id, "Module Gating Project OK")
    db = SessionLocal()
    try:
        admin_user = _get_admin_user(db)
        dependency = require_project_module_enabled(fake_module)
        result = dependency(
            project_id=uuid_lib.UUID(project["id"]), request=_FakeRequest(), current_user=admin_user, db=db
        )
        assert result.id == admin_user.id
    finally:
        db.close()


# --- Registry merge logic ----------------------------------------------------


def test_build_registry_merges_entry_point_modules_when_allowed(monkeypatch):
    entry_point_module = _fake_module(key="entry_point_fake_allowed", name="Entry Point Fake Allowed")
    monkeypatch.setattr(module_registry, "_discover_entry_point_modules", lambda: [entry_point_module])
    monkeypatch.setenv("ALLOW_EXTERNAL_MODULES", "true")
    get_settings.cache_clear()
    try:
        registry = build_registry(force=True)
        assert "entry_point_fake_allowed" in registry
        assert registry["entry_point_fake_allowed"].name == "Entry Point Fake Allowed"
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()
        build_registry(force=True)


def test_build_registry_excludes_entry_point_modules_when_disallowed(monkeypatch):
    entry_point_module = _fake_module(key="entry_point_fake_disallowed", name="Entry Point Fake Disallowed")
    monkeypatch.setattr(module_registry, "_discover_entry_point_modules", lambda: [entry_point_module])
    monkeypatch.delenv("ALLOW_EXTERNAL_MODULES", raising=False)
    get_settings.cache_clear()
    try:
        registry = build_registry(force=True)
        assert "entry_point_fake_disallowed" not in registry
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()
        build_registry(force=True)


def test_installed_modules_always_win_over_a_colliding_external_key(monkeypatch):
    installed = _fake_module(key="collision_key_test", name="Installed Wins")
    external = _fake_module(key="collision_key_test", name="External Loses")
    module_registry.INSTALLED_MODULES.append(installed)
    monkeypatch.setattr(module_registry, "_discover_entry_point_modules", lambda: [external])
    monkeypatch.setenv("ALLOW_EXTERNAL_MODULES", "true")
    get_settings.cache_clear()
    try:
        registry = build_registry(force=True)
        assert registry["collision_key_test"].name == "Installed Wins"
    finally:
        module_registry.INSTALLED_MODULES[:] = [
            m for m in module_registry.INSTALLED_MODULES if m.key != "collision_key_test"
        ]
        monkeypatch.undo()
        get_settings.cache_clear()
        build_registry(force=True)


def test_allow_external_modules_false_never_calls_discovery_functions(monkeypatch):
    """Confirms sources 2/3 aren't merely filtered afterward when the flag
    is off, but never even invoked — monkeypatching both discovery
    functions to raise, then confirming `build_registry` doesn't raise."""

    def _boom_entry_points():
        raise AssertionError("_discover_entry_point_modules must not be called when ALLOW_EXTERNAL_MODULES is false")

    def _boom_path(path_str):
        raise AssertionError("_discover_path_modules must not be called when ALLOW_EXTERNAL_MODULES is false")

    monkeypatch.setattr(module_registry, "_discover_entry_point_modules", _boom_entry_points)
    monkeypatch.setattr(module_registry, "_discover_path_modules", _boom_path)
    monkeypatch.delenv("ALLOW_EXTERNAL_MODULES", raising=False)
    monkeypatch.setenv("EXTRA_MODULES_PATH", "/some/path/that/would/trigger/discovery/if/called")
    get_settings.cache_clear()
    try:
        build_registry(force=True)  # must not raise
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()
        build_registry(force=True)


# --- Org-admin endpoints (/orgs/{id}/modules) --------------------------------


def test_org_modules_get_403_for_non_admin(client, admin_token, org_id, fake_module):
    create_org_user(client, admin_token, org_id, "plain_modules_reader@example.com", role="member")
    token = login(client, "plain_modules_reader@example.com", "Password123!")
    resp = client.get(f"/api/v1/orgs/{org_id}/modules", headers=auth_headers(token))
    assert resp.status_code == 403


def test_org_modules_put_403_for_non_admin(client, admin_token, org_id, fake_module):
    create_org_user(client, admin_token, org_id, "plain_modules_writer@example.com", role="member")
    token = login(client, "plain_modules_writer@example.com", "Password123!")
    resp = client.put(
        f"/api/v1/orgs/{org_id}/modules/{fake_module}", json={"enabled": False}, headers=auth_headers(token)
    )
    assert resp.status_code == 403


def test_org_admin_cannot_enable_a_non_entitled_module(client, admin_token, org_id, fake_module):
    db = SessionLocal()
    try:
        db.add(
            OrganizationModuleEntitlement(
                organization_id=uuid_lib.UUID(org_id), module_key=fake_module, entitled=False
            )
        )
        db.commit()
    finally:
        db.close()

    resp = client.put(
        f"/api/v1/orgs/{org_id}/modules/{fake_module}", json={"enabled": True}, headers=auth_headers(admin_token)
    )
    assert resp.status_code == 403
    assert "not entitled" in resp.json()["detail"].lower()


def test_org_modules_put_404_for_unregistered_module(client, admin_token, org_id):
    resp = client.put(
        f"/api/v1/orgs/{org_id}/modules/no-such-module", json={"enabled": True}, headers=auth_headers(admin_token)
    )
    assert resp.status_code == 404


def test_org_admin_can_toggle_an_entitled_module_and_it_is_audit_logged(client, admin_token, org_id, fake_module):
    resp = client.put(
        f"/api/v1/orgs/{org_id}/modules/{fake_module}", json={"enabled": False}, headers=auth_headers(admin_token)
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["enabled"] is False
    assert body["entitled"] is True

    db = SessionLocal()
    try:
        event = db.query(AuditEvent).filter(AuditEvent.action == "module.enablement_updated").first()
        assert event is not None
        assert event.detail["module_key"] == fake_module
        assert event.detail["enabled"] is False
    finally:
        db.close()


# --- Server-tier endpoints ----------------------------------------------------


def test_system_modules_requires_module_administrator_or_server_admin(client, admin_token, org_id, fake_module):
    create_org_user(client, admin_token, org_id, "plain_system_modules@example.com", role="member")
    token = login(client, "plain_system_modules@example.com", "Password123!")
    resp = client.get("/api/v1/system/modules", headers=auth_headers(token))
    assert resp.status_code == 403

    resp = client.get("/api/v1/system/modules", headers=auth_headers(admin_token))
    assert resp.status_code == 200
    assert fake_module in {m["module_key"] for m in resp.json()}


def test_org_admin_alone_cannot_access_system_module_endpoints(client, admin_token, fake_module):
    """Org admin is a different tier entirely from `MODULE_ADMINISTRATOR`/
    `SERVER_ADMIN` — must not implicitly satisfy this server-tier check."""
    _, other_admin_token = create_org_admin_in(client, admin_token, "Org For Module Registry Server Check")
    resp = client.get("/api/v1/system/modules", headers=auth_headers(other_admin_token))
    assert resp.status_code == 403


def test_module_administrator_can_use_the_full_server_tier_module_surface(client, admin_token, org_id, fake_module):
    user_id = create_org_user(client, admin_token, org_id, "module_admin_for_registry@example.com", role="member")
    resp = client.post(
        f"/api/v1/system/users/{user_id}/server-roles", json={"role": "module_administrator"},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 204
    token = login(client, "module_admin_for_registry@example.com", "Password123!")

    assert client.get("/api/v1/system/modules", headers=auth_headers(token)).status_code == 200
    assert client.get(
        f"/api/v1/system/orgs/{org_id}/module-entitlements", headers=auth_headers(token)
    ).status_code == 200

    resp = client.put(
        f"/api/v1/system/orgs/{org_id}/module-entitlements/{fake_module}", json={"entitled": False},
        headers=auth_headers(token),
    )
    assert resp.status_code == 200
    assert resp.json()["entitled"] is False
    assert resp.json()["has_override"] is True


def test_system_org_module_entitlements_404_for_unknown_org(client, admin_token, fake_module):
    resp = client.get(
        f"/api/v1/system/orgs/{uuid_lib.uuid4()}/module-entitlements", headers=auth_headers(admin_token)
    )
    assert resp.status_code == 404

    resp = client.put(
        f"/api/v1/system/orgs/{uuid_lib.uuid4()}/module-entitlements/{fake_module}", json={"entitled": True},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 404


def test_system_org_module_entitlements_404_for_unknown_module_key(client, admin_token, org_id):
    resp = client.put(
        f"/api/v1/system/orgs/{org_id}/module-entitlements/no-such-module", json={"entitled": True},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 404


def test_system_org_module_entitlements_reflects_override_state(client, admin_token, org_id, fake_module):
    resp = client.get(f"/api/v1/system/orgs/{org_id}/module-entitlements", headers=auth_headers(admin_token))
    assert resp.status_code == 200
    by_key = {m["module_key"]: m for m in resp.json()}
    assert by_key[fake_module]["entitled"] is True
    assert by_key[fake_module]["has_override"] is False
    assert by_key[fake_module]["default_policy_used"] is True

    resp = client.put(
        f"/api/v1/system/orgs/{org_id}/module-entitlements/{fake_module}", json={"entitled": False},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 200
    assert resp.json()["entitled"] is False
    assert resp.json()["has_override"] is True
    assert resp.json()["default_policy_used"] is False

    resp = client.get(f"/api/v1/system/orgs/{org_id}/module-entitlements", headers=auth_headers(admin_token))
    by_key = {m["module_key"]: m for m in resp.json()}
    assert by_key[fake_module]["entitled"] is False
    assert by_key[fake_module]["has_override"] is True
