"""Tests for Module 0 (Platform Foundations) Phase 4's module
sub-component enablement mechanism (`docs/plans/module-00-platform-
foundations-plan.md`): `ModuleSubComponentDefinition`, the two-tier
resolution functions (`app.modules.registry.is_module_subcomponent_enabled`/
`is_org_module_subcomponent_enabled`), the `require_project_subcomponent_
enabled`/`require_org_subcomponent_enabled` RBAC dependencies' 404-not-403
behaviour, and the org-tier (`/orgs/{id}/modules/{key}/subcomponents`) and
project-tier (`/projects/{id}/modules/{key}/subcomponents`) admin
endpoints.

Uses a fake `ModuleDefinition` with `sub_components` set (mirroring
`test_module_registry.py`'s own `fake_module` fixture pattern), not a real
content module, so this suite doesn't depend on Context & Strategy
existing — see `backend/app/modules/context_strategy/tests/
test_context_strategy_api.py` for the real end-to-end coverage of the
Strategy artefact actually wired onto this mechanism."""

import uuid as uuid_lib
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.database import SessionLocal
from app.models.module import OrganizationModuleSubComponentDefault, ProjectModuleSubComponentEnablement
from app.models.user import User
from app.modules import registry as module_registry
from app.modules.registry import (
    ModuleDefinition,
    ModuleSubComponentDefinition,
    build_registry,
    is_module_subcomponent_enabled,
    is_org_module_subcomponent_enabled,
)
from app.services.rbac import require_org_subcomponent_enabled, require_project_subcomponent_enabled
from tests.conftest import auth_headers, create_project

FAKE_MODULE_KEY = "fake_subcomponent_test_module"
SUBCOMPONENT_KEY = "widget"
OTHER_SUBCOMPONENT_KEY = "gadget"


class _FakeRequest:
    """Minimal stand-in for FastAPI's `Request` — see `test_module_
    registry.py`'s identical helper for why this is enough for the RBAC
    dependencies under test to be called directly."""

    def __init__(self):
        self.state = SimpleNamespace()


def _fake_module(**overrides) -> ModuleDefinition:
    defaults = dict(
        key=FAKE_MODULE_KEY, name="Fake Sub-Component Test Module",
        description="A fixture module registered only for this test file's own assertions.",
        version="0.0.1", default_enabled=True, implemented=False, get_router=lambda: None,
        sub_components=(
            ModuleSubComponentDefinition(key=SUBCOMPONENT_KEY, name="Widget", default_enabled=True),
            ModuleSubComponentDefinition(key=OTHER_SUBCOMPONENT_KEY, name="Gadget", default_enabled=False),
        ),
    )
    defaults.update(overrides)
    return ModuleDefinition(**defaults)


@pytest.fixture
def fake_module():
    """Registers a fake module (with two `sub_components`) into
    `INSTALLED_MODULES` for the duration of one test, rebuilding the
    registry cache before and after — mirrors `test_module_registry.py`'s
    own `fake_module` fixture exactly."""
    module_registry.INSTALLED_MODULES.append(_fake_module())
    build_registry(force=True)
    yield FAKE_MODULE_KEY
    module_registry.INSTALLED_MODULES[:] = [
        m for m in module_registry.INSTALLED_MODULES if m.key != FAKE_MODULE_KEY
    ]
    build_registry(force=True)


def _get_admin_user(db) -> User:
    return db.query(User).filter(User.email == "admin@example.com").first()


# --- is_module_subcomponent_enabled (project-scoped): all four resolution paths --------


def test_project_subcomponent_resolution_all_paths(client, admin_token, org_id, fake_module):
    project = create_project(client, admin_token, org_id, "Sub-Component Resolution Project")
    db = SessionLocal()
    try:
        org_uuid = uuid_lib.UUID(org_id)
        project_uuid = uuid_lib.UUID(project["id"])
        # Drop the rows copied in at creation, modelling a project created
        # before the module was registered (the only case with no row).
        db.query(ProjectModuleSubComponentEnablement).filter(
            ProjectModuleSubComponentEnablement.project_id == project_uuid,
        ).delete()
        db.commit()

        # (a) registry default — no org row, no project row.
        assert is_module_subcomponent_enabled(db, project_uuid, fake_module, SUBCOMPONENT_KEY) is True
        assert is_module_subcomponent_enabled(db, project_uuid, fake_module, OTHER_SUBCOMPONENT_KEY) is False

        # (b) org `default_project_enabled` overrides the registry default.
        org_row = OrganizationModuleSubComponentDefault(
            organization_id=org_uuid, module_key=fake_module, subcomponent_key=SUBCOMPONENT_KEY,
            enabled=True, default_project_enabled=False,
        )
        db.add(org_row)
        db.commit()
        assert is_module_subcomponent_enabled(db, project_uuid, fake_module, SUBCOMPONENT_KEY) is False

        # (c) project row overrides the org default (within the floor).
        db.add(
            ProjectModuleSubComponentEnablement(
                project_id=project_uuid, module_key=fake_module, subcomponent_key=SUBCOMPONENT_KEY, enabled=True,
            )
        )
        db.commit()
        assert is_module_subcomponent_enabled(db, project_uuid, fake_module, SUBCOMPONENT_KEY) is True

        # (d) org sub-component hard floor beats the project row.
        org_row.enabled = False
        db.commit()
        assert is_module_subcomponent_enabled(db, project_uuid, fake_module, SUBCOMPONENT_KEY) is False

        # (e) whole-module-disabled beats everything.
        org_row.enabled = True
        from app.models.module import OrganizationModuleEnablement

        db.add(OrganizationModuleEnablement(organization_id=org_uuid, module_key=fake_module, enabled=False, default_project_enabled=False))
        db.commit()
        assert is_module_subcomponent_enabled(db, project_uuid, fake_module, SUBCOMPONENT_KEY) is False
    finally:
        db.close()


def test_project_subcomponent_unregistered_key_behaves_as_disabled(client, admin_token, org_id, fake_module):
    project = create_project(client, admin_token, org_id, "Sub-Component Unregistered Key Project")
    db = SessionLocal()
    try:
        assert is_module_subcomponent_enabled(
            db, uuid_lib.UUID(project["id"]), fake_module, "no_such_subcomponent"
        ) is False
        assert is_module_subcomponent_enabled(
            db, uuid_lib.UUID(project["id"]), "no_such_module_at_all", SUBCOMPONENT_KEY
        ) is False
    finally:
        db.close()


# --- is_org_module_subcomponent_enabled (org-scoped): no project tier ------------------


def test_org_subcomponent_resolution_no_project_tier(client, admin_token, org_id, fake_module):
    db = SessionLocal()
    try:
        org_uuid = uuid_lib.UUID(org_id)

        # Registry default.
        assert is_org_module_subcomponent_enabled(db, org_uuid, fake_module, SUBCOMPONENT_KEY) is True
        assert is_org_module_subcomponent_enabled(db, org_uuid, fake_module, OTHER_SUBCOMPONENT_KEY) is False

        # Org default overrides the registry default directly (no project
        # tier exists above it for an org-scoped artefact).
        # `default_project_enabled` is irrelevant here — only `enabled` counts.
        db.add(
            OrganizationModuleSubComponentDefault(
                organization_id=org_uuid, module_key=fake_module, subcomponent_key=SUBCOMPONENT_KEY,
                enabled=False, default_project_enabled=True,
            )
        )
        db.commit()
        assert is_org_module_subcomponent_enabled(db, org_uuid, fake_module, SUBCOMPONENT_KEY) is False

        # Whole-module-disabled still overrides the org default.
        from app.models.module import OrganizationModuleEnablement

        db.add(OrganizationModuleEnablement(organization_id=org_uuid, module_key=fake_module, enabled=False, default_project_enabled=False))
        db.commit()
        assert is_org_module_subcomponent_enabled(db, org_uuid, fake_module, SUBCOMPONENT_KEY) is False
    finally:
        db.close()


# --- require_project_subcomponent_enabled / require_org_subcomponent_enabled -----------


def test_require_project_subcomponent_enabled_404_when_disabled(client, admin_token, org_id, fake_module):
    project = create_project(client, admin_token, org_id, "Require Project Subcomponent Disabled")
    db = SessionLocal()
    try:
        admin_user = _get_admin_user(db)
        dependency = require_project_subcomponent_enabled(fake_module, OTHER_SUBCOMPONENT_KEY)
        with pytest.raises(HTTPException) as exc_info:
            dependency(
                project_id=uuid_lib.UUID(project["id"]), request=_FakeRequest(), current_user=admin_user, db=db
            )
        assert exc_info.value.status_code == 404
    finally:
        db.close()


def test_require_project_subcomponent_enabled_passes_when_enabled(client, admin_token, org_id, fake_module):
    project = create_project(client, admin_token, org_id, "Require Project Subcomponent Enabled")
    db = SessionLocal()
    try:
        admin_user = _get_admin_user(db)
        dependency = require_project_subcomponent_enabled(fake_module, SUBCOMPONENT_KEY)
        result = dependency(
            project_id=uuid_lib.UUID(project["id"]), request=_FakeRequest(), current_user=admin_user, db=db
        )
        assert result.id == admin_user.id
    finally:
        db.close()


def test_require_org_subcomponent_enabled_404_when_disabled(client, admin_token, org_id, fake_module):
    db = SessionLocal()
    try:
        admin_user = _get_admin_user(db)
        dependency = require_org_subcomponent_enabled(fake_module, OTHER_SUBCOMPONENT_KEY)
        with pytest.raises(HTTPException) as exc_info:
            dependency(organization_id=uuid_lib.UUID(org_id), request=_FakeRequest(), current_user=admin_user, db=db)
        assert exc_info.value.status_code == 404
    finally:
        db.close()


def test_require_org_subcomponent_enabled_passes_when_enabled(client, admin_token, org_id, fake_module):
    db = SessionLocal()
    try:
        admin_user = _get_admin_user(db)
        dependency = require_org_subcomponent_enabled(fake_module, SUBCOMPONENT_KEY)
        result = dependency(
            organization_id=uuid_lib.UUID(org_id), request=_FakeRequest(), current_user=admin_user, db=db
        )
        assert result.id == admin_user.id
    finally:
        db.close()


# --- Org-tier admin endpoints -----------------------------------------------------------


def test_org_subcomponents_endpoint_lists_and_updates(client, admin_token, org_id, fake_module):
    resp = client.get(f"/api/v1/orgs/{org_id}/modules/{fake_module}/subcomponents", headers=auth_headers(admin_token))
    assert resp.status_code == 200, resp.text
    by_key = {row["subcomponent_key"]: row for row in resp.json()}
    assert by_key[SUBCOMPONENT_KEY]["default_enabled"] is True
    assert by_key[SUBCOMPONENT_KEY]["enabled"] is True
    assert by_key[SUBCOMPONENT_KEY]["default_project_enabled"] is True
    assert by_key[SUBCOMPONENT_KEY]["has_org_override"] is False
    assert by_key[OTHER_SUBCOMPONENT_KEY]["default_enabled"] is False

    resp = client.put(
        f"/api/v1/orgs/{org_id}/modules/{fake_module}/subcomponents/{SUBCOMPONENT_KEY}",
        json={"enabled": False}, headers=auth_headers(admin_token),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["enabled"] is False
    # Omitted on a new row -> matches `enabled`.
    assert body["default_project_enabled"] is False
    assert body["has_org_override"] is True
    assert body["default_enabled"] is True  # registry default is unaffected by the org's own choice

    # Omitted on an existing row -> left untouched; explicit value updates it.
    resp = client.put(
        f"/api/v1/orgs/{org_id}/modules/{fake_module}/subcomponents/{SUBCOMPONENT_KEY}",
        json={"enabled": True}, headers=auth_headers(admin_token),
    )
    assert resp.json()["default_project_enabled"] is False
    resp = client.put(
        f"/api/v1/orgs/{org_id}/modules/{fake_module}/subcomponents/{SUBCOMPONENT_KEY}",
        json={"enabled": True, "default_project_enabled": True}, headers=auth_headers(admin_token),
    )
    assert resp.json()["default_project_enabled"] is True

    resp = client.get(f"/api/v1/orgs/{org_id}/modules/{fake_module}/subcomponents", headers=auth_headers(admin_token))
    by_key = {row["subcomponent_key"]: row for row in resp.json()}
    assert by_key[SUBCOMPONENT_KEY]["enabled"] is True
    assert by_key[SUBCOMPONENT_KEY]["default_project_enabled"] is True
    assert by_key[SUBCOMPONENT_KEY]["has_org_override"] is True


def test_org_subcomponents_endpoint_404_for_unregistered_module_or_key(client, admin_token, org_id, fake_module):
    resp = client.get(
        f"/api/v1/orgs/{org_id}/modules/no_such_module/subcomponents", headers=auth_headers(admin_token)
    )
    assert resp.status_code == 404

    resp = client.put(
        f"/api/v1/orgs/{org_id}/modules/{fake_module}/subcomponents/no_such_key",
        json={"enabled": True}, headers=auth_headers(admin_token),
    )
    assert resp.status_code == 404


# --- Project-tier admin endpoints -------------------------------------------------------


def test_project_subcomponents_endpoint_lists_and_updates(client, admin_token, org_id, fake_module):
    """A project starts with the org's default copied in, and may opt in
    past an org default of off while the org's hard floor is on."""
    resp = client.put(
        f"/api/v1/orgs/{org_id}/modules/{fake_module}/subcomponents/{SUBCOMPONENT_KEY}",
        json={"enabled": True, "default_project_enabled": False}, headers=auth_headers(admin_token),
    )
    assert resp.status_code == 200, resp.text
    project_id = create_project(client, admin_token, org_id, "Project Sub-Component Endpoint Project")["id"]

    resp = client.get(
        f"/api/v1/projects/{project_id}/modules/{fake_module}/subcomponents", headers=auth_headers(admin_token)
    )
    assert resp.status_code == 200, resp.text
    by_key = {row["subcomponent_key"]: row for row in resp.json()}
    assert by_key[SUBCOMPONENT_KEY]["effective_enabled"] is False
    assert by_key[SUBCOMPONENT_KEY]["org_default_enabled"] is False
    assert by_key[SUBCOMPONENT_KEY]["org_hard_enabled"] is True
    assert by_key[SUBCOMPONENT_KEY]["project_override_enabled"] is False

    resp = client.put(
        f"/api/v1/projects/{project_id}/modules/{fake_module}/subcomponents/{SUBCOMPONENT_KEY}",
        json={"enabled": True}, headers=auth_headers(admin_token),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["effective_enabled"] is True
    assert body["org_default_enabled"] is False
    assert body["project_override_enabled"] is True


def test_project_subcomponents_endpoint_404_for_unregistered_module_or_key(client, admin_token, org_id, fake_module):
    project = create_project(client, admin_token, org_id, "Project Sub-Component 404 Project")
    project_id = project["id"]

    resp = client.get(
        f"/api/v1/projects/{project_id}/modules/no_such_module/subcomponents", headers=auth_headers(admin_token)
    )
    assert resp.status_code == 404

    resp = client.put(
        f"/api/v1/projects/{project_id}/modules/{fake_module}/subcomponents/no_such_key",
        json={"enabled": True}, headers=auth_headers(admin_token),
    )
    assert resp.status_code == 404
