"""Tests for Module 0 (Platform Foundations) Phase 5's project-level
override of whole-module enablement (`docs/plans/module-00-platform-
foundations-plan.md`): `ProjectModuleEnablement`, `app.modules.registry.
is_module_enabled_for_project`'s four-path resolution (registry default;
org default overriding registry default; project override overriding org
default, symmetric in either direction; entitlement as an absolute
ceiling no override can cross), `require_project_module_enabled`/
`require_project_module_enabled_dynamic`'s switch onto it, the project-tier
`GET`/`PUT /projects/{id}/modules/{module_key}` endpoints, and — the one
part of this phase that isn't purely additive — the regression proving a
project-level whole-module override correctly cascades into `is_module_
subcomponent_enabled`'s own resolution (Phase 4's own tests only proved
the org-level disable case cascades, a different code path now that this
phase's project-override tier sits ahead of it).

Uses a fake `ModuleDefinition` (mirroring `test_module_registry.py`'s own
`fake_module` fixture pattern), not a real content module, so this suite
doesn't depend on Context & Strategy existing."""

import uuid as uuid_lib
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.database import SessionLocal
from app.models.module import (
    OrganizationModuleEnablement,
    OrganizationModuleEntitlement,
    ProjectModuleEnablement,
)
from app.models.user import User
from app.modules import registry as module_registry
from app.modules.registry import (
    ModuleDefinition,
    ModuleSubComponentDefinition,
    build_registry,
    is_module_enabled_for_project,
    is_module_subcomponent_enabled,
)
from app.services.rbac import require_project_module_enabled, require_project_module_enabled_dynamic
from tests.conftest import auth_headers, create_org_admin_in, create_project

FAKE_MODULE_KEY = "fake_pme_test_module"
# Kept short deliberately: `update_org_module_enablement`'s audit-log call
# writes `entity_id=f"{organization_id}:{module_key}"` into `audit_events.
# entity_id` (VARCHAR(64), pre-existing core column) — a 36-char UUID plus
# colon already uses 37 of those, leaving 27 for `module_key`. Real
# registered module keys are short slugs ("compliance", "context_strategy"),
# so this is a fixture-naming constraint, not a product one; a longer key
# here previously overflowed the column (`StringDataRightTruncation`).
SUBCOMPONENT_KEY = "widget"


class _FakeRequest:
    """Minimal stand-in for FastAPI's `Request` — see `test_module_
    registry.py`'s identical helper."""

    def __init__(self):
        self.state = SimpleNamespace()


def _fake_module(**overrides) -> ModuleDefinition:
    defaults = dict(
        key=FAKE_MODULE_KEY, name="Fake Project Enablement Test Module",
        description="A fixture module registered only for this test file's own assertions.",
        version="0.0.1", default_enabled=True, implemented=False, get_router=lambda: None,
        sub_components=(ModuleSubComponentDefinition(key=SUBCOMPONENT_KEY, name="Widget", default_enabled=True),),
    )
    defaults.update(overrides)
    return ModuleDefinition(**defaults)


@pytest.fixture
def fake_module():
    """Registers a fake module into `INSTALLED_MODULES` for the duration
    of one test, rebuilding the registry cache before and after — mirrors
    `test_module_registry.py`'s own `fake_module` fixture exactly."""
    module_registry.INSTALLED_MODULES.append(_fake_module())
    build_registry(force=True)
    yield FAKE_MODULE_KEY
    module_registry.INSTALLED_MODULES[:] = [
        m for m in module_registry.INSTALLED_MODULES if m.key != FAKE_MODULE_KEY
    ]
    build_registry(force=True)


def _get_admin_user(db) -> User:
    return db.query(User).filter(User.email == "admin@example.com").first()


# --- is_module_enabled_for_project: all four resolution paths --------------------------


def test_project_enablement_resolution_all_four_paths(client, admin_token, org_id, fake_module):
    project = create_project(client, admin_token, org_id, "Project Whole-Module Enablement Resolution")
    db = SessionLocal()
    try:
        org_uuid = uuid_lib.UUID(org_id)
        project_uuid = uuid_lib.UUID(project["id"])

        # (a) registry default — no org row, no project row.
        assert is_module_enabled_for_project(db, project_uuid, fake_module) is True

        # (b) org default overrides the registry default.
        db.add(OrganizationModuleEnablement(organization_id=org_uuid, module_key=fake_module, enabled=False))
        db.commit()
        assert is_module_enabled_for_project(db, project_uuid, fake_module) is False

        # (c) project override overrides the org default — symmetric:
        # enabling a module the org default has turned off.
        db.add(ProjectModuleEnablement(project_id=project_uuid, module_key=fake_module, enabled=True))
        db.commit()
        assert is_module_enabled_for_project(db, project_uuid, fake_module) is True

        # Symmetric the other direction too: org default on, project
        # override off.
        db.query(OrganizationModuleEnablement).filter(
            OrganizationModuleEnablement.organization_id == org_uuid,
            OrganizationModuleEnablement.module_key == fake_module,
        ).delete()
        db.query(ProjectModuleEnablement).filter(
            ProjectModuleEnablement.project_id == project_uuid,
            ProjectModuleEnablement.module_key == fake_module,
        ).delete()
        db.commit()
        db.add(ProjectModuleEnablement(project_id=project_uuid, module_key=fake_module, enabled=False))
        db.commit()
        assert is_module_enabled_for_project(db, project_uuid, fake_module) is False

        # (d) entitlement is an absolute ceiling — overrides everything,
        # even a project override explicitly set to enabled=True.
        db.query(ProjectModuleEnablement).filter(
            ProjectModuleEnablement.project_id == project_uuid,
            ProjectModuleEnablement.module_key == fake_module,
        ).delete()
        db.add(ProjectModuleEnablement(project_id=project_uuid, module_key=fake_module, enabled=True))
        db.add(OrganizationModuleEntitlement(organization_id=org_uuid, module_key=fake_module, entitled=False))
        db.commit()
        assert is_module_enabled_for_project(db, project_uuid, fake_module) is False
    finally:
        db.close()


def test_project_enablement_unregistered_module_behaves_as_disabled(client, admin_token, org_id, fake_module):
    project = create_project(client, admin_token, org_id, "Project Whole-Module Unregistered")
    db = SessionLocal()
    try:
        assert is_module_enabled_for_project(db, uuid_lib.UUID(project["id"]), "no_such_module_at_all") is False
    finally:
        db.close()


# --- Cascade regression: a project-level whole-module override must cascade into
# --- is_module_subcomponent_enabled, not just the org-level disable case. --------------


def test_project_level_whole_module_override_cascades_to_subcomponent_resolution(
    client, admin_token, org_id, fake_module
):
    """The one part of Phase 5 that isn't purely additive: before this
    phase, `is_module_subcomponent_enabled` resolved whole-module state via
    the org-only `is_module_enabled`, so it could only ever see an
    org-level disable. Now that a project can independently disable the
    whole module via `ProjectModuleEnablement`, that override must also
    disable every one of that module's sub-components — proven here
    against a project where the *org* default is still enabled (the org-
    level disable path Phase 4's own tests already covered would pass
    even without this phase's fix; this test isolates the new code path)."""
    project = create_project(client, admin_token, org_id, "Subcomponent Cascade From Project Override")
    db = SessionLocal()
    try:
        project_uuid = uuid_lib.UUID(project["id"])

        # Org default for the whole module stays enabled (unset — registry
        # default_enabled=True) and the sub-component itself has no
        # override of its own — before any project-level whole-module
        # override, the sub-component is enabled.
        assert is_module_subcomponent_enabled(db, project_uuid, fake_module, SUBCOMPONENT_KEY) is True

        # A project-level *whole-module* override disables the module for
        # this project only (org default is untouched, still enabled).
        db.add(ProjectModuleEnablement(project_id=project_uuid, module_key=fake_module, enabled=False))
        db.commit()

        # The sub-component must now resolve to disabled too — this is
        # the cascade this phase's fix is responsible for.
        assert is_module_subcomponent_enabled(db, project_uuid, fake_module, SUBCOMPONENT_KEY) is False

        # Confirm this isn't a false negative from some other cause: a
        # sibling project with no such override still sees the
        # sub-component enabled.
        sibling_project = create_project(client, admin_token, org_id, "Subcomponent Cascade Sibling")
        assert is_module_subcomponent_enabled(
            db, uuid_lib.UUID(sibling_project["id"]), fake_module, SUBCOMPONENT_KEY
        ) is True

        # And re-enabling the module at the project level (symmetric
        # override) restores the sub-component's own resolution too.
        db.query(ProjectModuleEnablement).filter(
            ProjectModuleEnablement.project_id == project_uuid,
            ProjectModuleEnablement.module_key == fake_module,
        ).delete()
        db.add(ProjectModuleEnablement(project_id=project_uuid, module_key=fake_module, enabled=True))
        db.commit()
        assert is_module_subcomponent_enabled(db, project_uuid, fake_module, SUBCOMPONENT_KEY) is True
    finally:
        db.close()


# --- require_project_module_enabled / require_project_module_enabled_dynamic -----------


def test_require_project_module_enabled_404_when_project_override_disables(client, admin_token, org_id, fake_module):
    """Before this phase, only an org-level disable could 404 this
    dependency. Now a project-level override alone (org default left
    enabled) must too."""
    project = create_project(client, admin_token, org_id, "Require Project Module Enabled Override Disabled")
    db = SessionLocal()
    try:
        db.add(
            ProjectModuleEnablement(
                project_id=uuid_lib.UUID(project["id"]), module_key=fake_module, enabled=False,
            )
        )
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


def test_require_project_module_enabled_passes_when_project_override_enables_over_org_default_off(
    client, admin_token, org_id, fake_module
):
    """Symmetric direction: the org default is off, but this project's own
    override turns it on — the dependency must pass."""
    project = create_project(client, admin_token, org_id, "Require Project Module Enabled Override Enabled")
    db = SessionLocal()
    try:
        org_uuid = uuid_lib.UUID(org_id)
        project_uuid = uuid_lib.UUID(project["id"])
        db.add(OrganizationModuleEnablement(organization_id=org_uuid, module_key=fake_module, enabled=False))
        db.add(ProjectModuleEnablement(project_id=project_uuid, module_key=fake_module, enabled=True))
        db.commit()
        admin_user = _get_admin_user(db)
        dependency = require_project_module_enabled(fake_module)
        result = dependency(project_id=project_uuid, request=_FakeRequest(), current_user=admin_user, db=db)
        assert result.id == admin_user.id
    finally:
        db.close()


def test_require_project_module_enabled_dynamic_respects_project_override(client, admin_token, org_id, fake_module):
    project = create_project(client, admin_token, org_id, "Require Project Module Enabled Dynamic Override")
    db = SessionLocal()
    try:
        db.add(
            ProjectModuleEnablement(
                project_id=uuid_lib.UUID(project["id"]), module_key=fake_module, enabled=False,
            )
        )
        db.commit()
        admin_user = _get_admin_user(db)
        with pytest.raises(HTTPException) as exc_info:
            require_project_module_enabled_dynamic(
                project_id=uuid_lib.UUID(project["id"]), module_key=fake_module,
                request=_FakeRequest(), current_user=admin_user, db=db,
            )
        assert exc_info.value.status_code == 404
    finally:
        db.close()


# --- Project-tier whole-module admin endpoints ------------------------------------------


def test_project_module_enablement_endpoint_get_and_put(client, admin_token, org_id, fake_module):
    project = create_project(client, admin_token, org_id, "Project Module Enablement Endpoint Project")
    project_id = project["id"]

    resp = client.get(
        f"/api/v1/projects/{project_id}/modules/{fake_module}/enablement", headers=auth_headers(admin_token)
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["effective_enabled"] is True
    assert body["org_default_enabled"] is True
    assert body["has_project_override"] is False
    assert body["project_override_enabled"] is None

    # Set the org default to False first (via the existing whole-module
    # endpoint), then confirm the project view reflects it with no
    # override of its own yet.
    resp = client.put(
        f"/api/v1/orgs/{org_id}/modules/{fake_module}", json={"enabled": False}, headers=auth_headers(admin_token),
    )
    assert resp.status_code == 200, resp.text

    resp = client.get(
        f"/api/v1/projects/{project_id}/modules/{fake_module}/enablement", headers=auth_headers(admin_token)
    )
    body = resp.json()
    assert body["effective_enabled"] is False
    assert body["org_default_enabled"] is False
    assert body["has_project_override"] is False

    # A project-level override of True wins symmetrically over the org
    # default of False.
    resp = client.put(
        f"/api/v1/projects/{project_id}/modules/{fake_module}/enablement", json={"enabled": True},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["effective_enabled"] is True
    assert body["org_default_enabled"] is False
    assert body["has_project_override"] is True
    assert body["project_override_enabled"] is True

    resp = client.get(
        f"/api/v1/projects/{project_id}/modules/{fake_module}/enablement", headers=auth_headers(admin_token)
    )
    body = resp.json()
    assert body["effective_enabled"] is True
    assert body["has_project_override"] is True


def test_project_module_enablement_endpoint_404_for_unregistered_module(client, admin_token, org_id, fake_module):
    project = create_project(client, admin_token, org_id, "Project Module Enablement 404 Project")
    project_id = project["id"]

    resp = client.get(
        f"/api/v1/projects/{project_id}/modules/no_such_module/enablement", headers=auth_headers(admin_token)
    )
    assert resp.status_code == 404

    resp = client.put(
        f"/api/v1/projects/{project_id}/modules/no_such_module/enablement", json={"enabled": True},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 404


def test_project_module_enablement_endpoint_does_not_shadow_a_modules_own_bare_project_router_route(
    client, admin_token, org_id,
):
    """Regression for the routing collision this phase's own verification
    found and fixed: before the `/enablement` suffix was added, `GET/PUT
    /projects/{project_id}/modules/{module_key}` (registered on the core
    `routers.projects` router, mounted in `main.py` *before* any module's
    own `get_project_router()`) shadowed Decision Management's own bare
    `GET ""`/`POST ""` list/create routes at that exact path
    (`app.modules.decisions.project_router.core`) — a request to `GET
    /api/v1/projects/{project_id}/modules/decisions` silently returned
    this endpoint's `ProjectModuleEnablementOut` shape instead of the
    expected list of decisions. Exercised here against the real,
    registered `decisions` module (not a fake one), since the bug is about
    *route registration order* across the whole app, which a fake module
    appended to `INSTALLED_MODULES` at test time does not reproduce the
    same way a real, `main.py`-mounted module does."""
    org, org_admin_token = create_org_admin_in(client, admin_token, "Decisions Route Shadow Regression Co")
    resp = client.put(
        f"/api/v1/orgs/{org['id']}/modules/decisions", json={"enabled": True}, headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 200, resp.text
    project = create_project(client, org_admin_token, org["id"], "Decisions Route Shadow Regression Project")

    resp = client.get(
        f"/api/v1/projects/{project['id']}/modules/decisions", headers=auth_headers(org_admin_token)
    )
    assert resp.status_code == 200, resp.text
    # A real list-of-decisions response (initially empty), never this
    # phase's own `ProjectModuleEnablementOut` shape (which would instead
    # have `effective_enabled`/`org_default_enabled` keys).
    assert resp.json() == []
