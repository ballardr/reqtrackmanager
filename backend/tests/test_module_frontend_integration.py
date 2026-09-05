"""Tests for the module system's Phase 3 two-tier frontend integration
(docs/compliance-module-plan.md): `ModuleFrontendManifest`'s tier/frame_url
validation, `get_frontend_manifest`'s allowlist-enforcement (a Tier B
module's declared `frame_url` must resolve to an origin in `Settings.
module_frame_allowed_origins`, or it is excluded and logged rather than
trusted from the module's own declaration), the CSP `frame-src` header
built from that same allowlist, Tier B `<ModuleFrame>` token minting/
decoding (`app.security.create_module_frame_token`/`decode_module_frame_
token`), and the module-frame-token scope enforcement `app.services.rbac.
_enforce_module_frame_scope` adds to `require_org_module_enabled`/
`require_project_module_enabled`/`require_module_role`.

Every test that registers a fixture module into the process-global
`INSTALLED_MODULES` list follows `test_module_registry.py`'s own `fake_
module` fixture convention: always tears down by removing it and rebuilding
the registry cache, so this module-level mutable list never leaks state
into another test regardless of execution order."""

import uuid as uuid_lib
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.config import get_settings
from app.database import SessionLocal
from app.deps import get_current_user_or_module_frame
from app.models.user import User
from app.modules import registry as module_registry
from app.modules.registry import (
    ModuleDefinition,
    ModuleFrontendManifest,
    build_registry,
    get_frontend_manifest,
)
from app.security import create_module_frame_token, decode_module_frame_token
from app.services.rbac import require_module_role, require_org_module_enabled, require_project_module_enabled
from tests.conftest import auth_headers, create_project

INSTALLED_MODULE_KEY = "fake_frontend_installed_module"
REMOTE_MODULE_KEY = "fake_frontend_remote_module"
ALLOWED_ORIGIN = "https://trusted-module.example.com"
NOT_ALLOWED_ORIGIN = "https://untrusted-module.example.com"


class _FakeRequest:
    """Minimal stand-in for FastAPI's `Request` — same shape as
    `test_module_registry.py`'s own helper: just enough for `check_pat_
    scope`/`_enforce_module_frame_scope`'s `getattr(request.state, ...,
    None)` reads to behave correctly without the full FastAPI DI/HTTP
    stack."""

    def __init__(self):
        self.state = SimpleNamespace()


def _fake_module(**overrides) -> ModuleDefinition:
    defaults = dict(
        key=INSTALLED_MODULE_KEY, name="Fake Frontend Module",
        description="A fixture module registered only for this test file's own assertions.",
        version="0.0.1", default_enabled=True, implemented=False, get_router=lambda: None,
    )
    defaults.update(overrides)
    return ModuleDefinition(**defaults)


@pytest.fixture
def installed_tier_module():
    """Registers a Tier A ("installed") fixture module with a frontend
    manifest for the duration of one test."""
    module_registry.INSTALLED_MODULES.append(
        _fake_module(
            frontend_manifest=ModuleFrontendManifest(
                tier="installed", nav_label="Fake Frontend", nav_path="/fake-frontend"
            )
        )
    )
    build_registry(force=True)
    yield INSTALLED_MODULE_KEY
    module_registry.INSTALLED_MODULES[:] = [
        m for m in module_registry.INSTALLED_MODULES if m.key != INSTALLED_MODULE_KEY
    ]
    build_registry(force=True)


@pytest.fixture
def remote_tier_module():
    """Registers a Tier B ("remote") fixture module whose `frame_url`'s
    origin is `ALLOWED_ORIGIN` — callers control whether that origin is
    actually in `Settings.module_frame_allowed_origins` for a given test."""
    module_registry.INSTALLED_MODULES.append(
        _fake_module(
            key=REMOTE_MODULE_KEY, name="Fake Remote Module",
            frontend_manifest=ModuleFrontendManifest(
                tier="remote", nav_label="Fake Remote", nav_path="/fake-remote",
                frame_url=f"{ALLOWED_ORIGIN}/module-entry",
            ),
        )
    )
    build_registry(force=True)
    yield REMOTE_MODULE_KEY
    module_registry.INSTALLED_MODULES[:] = [
        m for m in module_registry.INSTALLED_MODULES if m.key != REMOTE_MODULE_KEY
    ]
    build_registry(force=True)


def _get_admin_user(db) -> User:
    return db.query(User).filter(User.email == "admin@example.com").first()


# --- ModuleFrontendManifest validation ---------------------------------------


def test_remote_tier_requires_frame_url():
    with pytest.raises(ValueError, match="requires frame_url"):
        ModuleFrontendManifest(tier="remote", nav_label="Bad", nav_path="/bad")


def test_installed_tier_must_not_set_frame_url():
    with pytest.raises(ValueError, match="must not set frame_url"):
        ModuleFrontendManifest(
            tier="installed", nav_label="Bad", nav_path="/bad", frame_url="https://example.com/x"
        )


# --- get_frontend_manifest / allowlist enforcement ---------------------------


def test_get_frontend_manifest_returns_installed_tier_manifest_unconditionally(installed_tier_module):
    manifest = get_frontend_manifest(installed_tier_module)
    assert manifest is not None
    assert manifest.tier == "installed"
    assert manifest.nav_label == "Fake Frontend"


def test_get_frontend_manifest_none_for_module_without_one(installed_tier_module):
    # A module with no frontend_manifest at all (the module system Phase 1/2
    # fixture shape) must not error — just report "nothing to show."
    module_registry.INSTALLED_MODULES.append(_fake_module(key="no_manifest_fake", frontend_manifest=None))
    build_registry(force=True)
    try:
        assert get_frontend_manifest("no_manifest_fake") is None
    finally:
        module_registry.INSTALLED_MODULES[:] = [
            m for m in module_registry.INSTALLED_MODULES if m.key != "no_manifest_fake"
        ]
        build_registry(force=True)


def test_get_frontend_manifest_none_for_unregistered_module():
    assert get_frontend_manifest("this_module_does_not_exist_anywhere") is None


def test_get_frontend_manifest_rejects_remote_tier_outside_allowlist(remote_tier_module, monkeypatch, caplog):
    monkeypatch.delenv("MODULE_FRAME_ALLOWED_ORIGINS", raising=False)
    get_settings.cache_clear()
    try:
        with caplog.at_level("WARNING"):
            manifest = get_frontend_manifest(remote_tier_module)
        assert manifest is None
        assert "not in MODULE_FRAME_ALLOWED_ORIGINS" in caplog.text
    finally:
        get_settings.cache_clear()


def test_get_frontend_manifest_accepts_remote_tier_inside_allowlist(remote_tier_module, monkeypatch):
    monkeypatch.setenv("MODULE_FRAME_ALLOWED_ORIGINS", ALLOWED_ORIGIN)
    get_settings.cache_clear()
    try:
        manifest = get_frontend_manifest(remote_tier_module)
        assert manifest is not None
        assert manifest.tier == "remote"
        assert manifest.frame_url == f"{ALLOWED_ORIGIN}/module-entry"
    finally:
        get_settings.cache_clear()


def test_get_frontend_manifest_rejects_a_different_allowlisted_origin(remote_tier_module, monkeypatch):
    # ALLOWED_ORIGIN's module declares a frame_url on ALLOWED_ORIGIN; a
    # deployment that only trusts a *different* origin must still exclude it.
    monkeypatch.setenv("MODULE_FRAME_ALLOWED_ORIGINS", NOT_ALLOWED_ORIGIN)
    get_settings.cache_clear()
    try:
        assert get_frontend_manifest(remote_tier_module) is None
    finally:
        get_settings.cache_clear()


# --- CSP frame-src header -----------------------------------------------------


def test_csp_frame_src_defaults_to_none(client, monkeypatch):
    monkeypatch.delenv("MODULE_FRAME_ALLOWED_ORIGINS", raising=False)
    get_settings.cache_clear()
    try:
        resp = client.get("/api/v1/health")
        assert "frame-src 'none'" in resp.headers["content-security-policy"]
        assert "frame-ancestors 'none'" in resp.headers["content-security-policy"]
    finally:
        get_settings.cache_clear()


def test_csp_frame_src_reflects_configured_allowlist(client, monkeypatch):
    monkeypatch.setenv("MODULE_FRAME_ALLOWED_ORIGINS", f"{ALLOWED_ORIGIN},{NOT_ALLOWED_ORIGIN}")
    get_settings.cache_clear()
    try:
        resp = client.get("/api/v1/health")
        csp = resp.headers["content-security-policy"]
        assert ALLOWED_ORIGIN in csp
        assert NOT_ALLOWED_ORIGIN in csp
    finally:
        get_settings.cache_clear()


# --- Frame-token minting endpoints --------------------------------------------


def test_org_frame_token_endpoint_mints_a_scoped_token(client, admin_token, org_id, installed_tier_module):
    resp = client.post(
        f"/api/v1/orgs/{org_id}/modules/{installed_tier_module}/frame-token", headers=auth_headers(admin_token)
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["expires_in_minutes"] == 15
    claims = decode_module_frame_token(body["token"])
    assert claims is not None
    assert claims["module_key"] == installed_tier_module
    assert claims["organization_id"] == org_id
    assert claims["project_id"] is None
    assert claims["purpose"] == "module_frame"


def test_org_frame_token_endpoint_404_for_disabled_module(client, admin_token, org_id, installed_tier_module):
    from app.models.module import OrganizationModuleEnablement

    db = SessionLocal()
    try:
        db.add(
            OrganizationModuleEnablement(
                organization_id=uuid_lib.UUID(org_id), module_key=installed_tier_module, enabled=False
            )
        )
        db.commit()
    finally:
        db.close()

    resp = client.post(
        f"/api/v1/orgs/{org_id}/modules/{installed_tier_module}/frame-token", headers=auth_headers(admin_token)
    )
    assert resp.status_code == 404


def test_org_frame_token_endpoint_404_for_unregistered_module(client, admin_token, org_id):
    resp = client.post(
        f"/api/v1/orgs/{org_id}/modules/no-such-module/frame-token", headers=auth_headers(admin_token)
    )
    assert resp.status_code == 404


def test_project_frame_token_endpoint_mints_a_token_scoped_to_the_project(
    client, admin_token, org_id, installed_tier_module
):
    project = create_project(client, admin_token, org_id, "Module Frame Token Project")
    resp = client.post(
        f"/api/v1/projects/{project['id']}/modules/{installed_tier_module}/frame-token",
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 200
    claims = decode_module_frame_token(resp.json()["token"])
    assert claims["module_key"] == installed_tier_module
    assert claims["organization_id"] == org_id
    assert claims["project_id"] == project["id"]


def test_a_module_frame_token_cannot_mint_another_token(client, admin_token, org_id, installed_tier_module):
    """A Tier B iframe's own scoped token must never be usable to mint
    itself a broader or different token — the minting endpoints depend on
    plain `get_current_user`, which rejects any non-`"access"`-purpose
    token outright, same as it already rejects a 2FA challenge token."""
    admin_user_id = None
    db = SessionLocal()
    try:
        admin_user_id = str(_get_admin_user(db).id)
    finally:
        db.close()
    frame_token = create_module_frame_token(
        module_key=installed_tier_module, organization_id=org_id, user_id=admin_user_id
    )
    resp = client.post(
        f"/api/v1/orgs/{org_id}/modules/{installed_tier_module}/frame-token",
        headers=auth_headers(frame_token),
    )
    assert resp.status_code == 401


# --- get_current_user_or_module_frame -----------------------------------------


def test_get_current_user_or_module_frame_resolves_a_valid_frame_token(client, admin_token, org_id, installed_tier_module):
    db = SessionLocal()
    try:
        admin_user = _get_admin_user(db)
        token = create_module_frame_token(
            module_key=installed_tier_module, organization_id=org_id, user_id=str(admin_user.id)
        )
        request = _FakeRequest()
        dependency = get_current_user_or_module_frame(installed_tier_module)
        result = dependency(request=request, token=token, db=db)
        assert result.id == admin_user.id
        assert request.state.module_frame_scope == {"organization_id": org_id, "project_id": None}
    finally:
        db.close()


def test_get_current_user_or_module_frame_rejects_wrong_module_key(client, admin_token, org_id, installed_tier_module):
    db = SessionLocal()
    try:
        admin_user = _get_admin_user(db)
        token = create_module_frame_token(
            module_key="a_totally_different_module", organization_id=org_id, user_id=str(admin_user.id)
        )
        dependency = get_current_user_or_module_frame(installed_tier_module)
        with pytest.raises(HTTPException) as exc_info:
            dependency(request=_FakeRequest(), token=token, db=db)
        assert exc_info.value.status_code == 401
    finally:
        db.close()


def test_get_current_user_or_module_frame_still_accepts_a_normal_access_token(
    client, admin_token, org_id, installed_tier_module
):
    """A normal session token must keep working through this dependency
    exactly as it would through plain `get_current_user` — Tier A callers
    never mint or use a module-frame token at all."""
    db = SessionLocal()
    try:
        request = _FakeRequest()
        dependency = get_current_user_or_module_frame(installed_tier_module)
        result = dependency(request=request, token=admin_token, db=db)
        assert result.email == "admin@example.com"
        assert getattr(request.state, "module_frame_scope", None) is None
    finally:
        db.close()


# --- Module-frame scope enforcement on the gating dependencies ---------------


def test_require_org_module_enabled_rejects_a_token_scoped_to_a_different_org(
    client, admin_token, org_id, installed_tier_module
):
    db = SessionLocal()
    try:
        admin_user = _get_admin_user(db)
        other_org_id = str(uuid_lib.uuid4())
        request = _FakeRequest()
        request.state.module_frame_scope = {"organization_id": other_org_id, "project_id": None}
        dependency = require_org_module_enabled(installed_tier_module)
        with pytest.raises(HTTPException) as exc_info:
            dependency(organization_id=uuid_lib.UUID(org_id), request=request, current_user=admin_user, db=db)
        assert exc_info.value.status_code == 403
    finally:
        db.close()


def test_require_org_module_enabled_accepts_a_token_scoped_to_the_matching_org(
    client, admin_token, org_id, installed_tier_module
):
    db = SessionLocal()
    try:
        admin_user = _get_admin_user(db)
        request = _FakeRequest()
        request.state.module_frame_scope = {"organization_id": org_id, "project_id": None}
        dependency = require_org_module_enabled(installed_tier_module)
        result = dependency(organization_id=uuid_lib.UUID(org_id), request=request, current_user=admin_user, db=db)
        assert result.id == admin_user.id
    finally:
        db.close()


def test_require_project_module_enabled_rejects_an_org_scoped_token(client, admin_token, org_id, installed_tier_module):
    """An org-minted token (`project_id: None`) must never satisfy a
    project-scoped module-gated endpoint, even for the token's own org."""
    project = create_project(client, admin_token, org_id, "Module Frame Scope Reject Project")
    db = SessionLocal()
    try:
        admin_user = _get_admin_user(db)
        request = _FakeRequest()
        request.state.module_frame_scope = {"organization_id": org_id, "project_id": None}
        dependency = require_project_module_enabled(installed_tier_module)
        with pytest.raises(HTTPException) as exc_info:
            dependency(project_id=uuid_lib.UUID(project["id"]), request=request, current_user=admin_user, db=db)
        assert exc_info.value.status_code == 403
    finally:
        db.close()


def test_require_project_module_enabled_accepts_a_token_scoped_to_the_matching_project(
    client, admin_token, org_id, installed_tier_module
):
    project = create_project(client, admin_token, org_id, "Module Frame Scope Accept Project")
    db = SessionLocal()
    try:
        admin_user = _get_admin_user(db)
        request = _FakeRequest()
        request.state.module_frame_scope = {"organization_id": org_id, "project_id": project["id"]}
        dependency = require_project_module_enabled(installed_tier_module)
        result = dependency(project_id=uuid_lib.UUID(project["id"]), request=request, current_user=admin_user, db=db)
        assert result.id == admin_user.id
    finally:
        db.close()


def test_require_module_role_scope_mismatch_403s_even_for_server_admin(client, admin_token, org_id):
    """The scope check runs before the `is_server_admin` bypass — a
    mis-scoped module-frame token must not be rescued by the fact that the
    underlying real user happens to be a server admin (the whole point of
    handing a remote module a narrower token instead of the real session
    token)."""
    from app.modules.registry import ModuleRoleDefinition

    role_module_key = "fake_role_scope_module"
    module_registry.INSTALLED_MODULES.append(
        _fake_module(
            key=role_module_key,
            roles=(ModuleRoleDefinition(role_key="fake_role", name="Fake Role", description="d", scope="org"),),
        )
    )
    build_registry(force=True)
    try:
        db = SessionLocal()
        try:
            admin_user = _get_admin_user(db)
            other_org_id = str(uuid_lib.uuid4())
            request = _FakeRequest()
            request.state.module_frame_scope = {"organization_id": other_org_id, "project_id": None}
            dependency = require_module_role(role_module_key, "fake_role")
            with pytest.raises(HTTPException) as exc_info:
                dependency(organization_id=uuid_lib.UUID(org_id), request=request, current_user=admin_user, db=db)
            assert exc_info.value.status_code == 403
        finally:
            db.close()
    finally:
        module_registry.INSTALLED_MODULES[:] = [
            m for m in module_registry.INSTALLED_MODULES if m.key != role_module_key
        ]
        build_registry(force=True)


# --- Nav-facing endpoints ------------------------------------------------------


def test_org_modules_endpoint_includes_frontend_manifest(client, admin_token, org_id, installed_tier_module):
    resp = client.get(f"/api/v1/orgs/{org_id}/modules", headers=auth_headers(admin_token))
    assert resp.status_code == 200
    by_key = {m["module_key"]: m for m in resp.json()}
    manifest = by_key[installed_tier_module]["frontend_manifest"]
    assert manifest == {
        "tier": "installed", "nav_label": "Fake Frontend", "nav_path": "/fake-frontend", "frame_url": None,
    }


def test_org_modules_endpoint_omits_manifest_for_a_rejected_remote_module(
    client, admin_token, org_id, remote_tier_module, monkeypatch
):
    monkeypatch.delenv("MODULE_FRAME_ALLOWED_ORIGINS", raising=False)
    get_settings.cache_clear()
    try:
        resp = client.get(f"/api/v1/orgs/{org_id}/modules", headers=auth_headers(admin_token))
        by_key = {m["module_key"]: m for m in resp.json()}
        assert by_key[remote_tier_module]["frontend_manifest"] is None
    finally:
        get_settings.cache_clear()


def test_project_enabled_modules_endpoint_lists_only_enabled_modules(
    client, admin_token, org_id, installed_tier_module
):
    from app.models.module import OrganizationModuleEnablement

    project = create_project(client, admin_token, org_id, "Enabled Modules Nav Project")
    resp = client.get(
        f"/api/v1/projects/{project['id']}/enabled-modules", headers=auth_headers(admin_token)
    )
    assert resp.status_code == 200
    by_key = {m["module_key"]: m for m in resp.json()}
    assert installed_tier_module in by_key
    assert by_key[installed_tier_module]["frontend_manifest"]["nav_label"] == "Fake Frontend"

    db = SessionLocal()
    try:
        db.add(
            OrganizationModuleEnablement(
                organization_id=uuid_lib.UUID(org_id), module_key=installed_tier_module, enabled=False
            )
        )
        db.commit()
    finally:
        db.close()

    resp = client.get(
        f"/api/v1/projects/{project['id']}/enabled-modules", headers=auth_headers(admin_token)
    )
    assert installed_tier_module not in {m["module_key"] for m in resp.json()}
