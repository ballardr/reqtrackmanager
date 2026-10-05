"""Tests for Module 0 (Platform Foundations) Phase 5's project-level
override of whole-module enablement (`docs/plans/module-00-platform-
foundations-plan.md`): `ProjectModuleEnablement`, `app.modules.registry.
is_module_enabled_for_project`'s resolution, `require_project_module_enabled`/
`require_project_module_enabled_dynamic`'s switch onto it, the project-tier
`GET`/`PUT /projects/{id}/modules/{module_key}/enablement` endpoints,
copy-on-create / copy-before-default-change (Decided by: User,
2026-10-04 — an org default only affects projects created afterwards; an
org hard Off still reaches every project), and — the one part of this phase that isn't purely additive —
the regression proving a project-level whole-module override correctly
cascades into `is_module_subcomponent_enabled`'s own resolution (Phase 4's
own tests only proved the org-level disable case cascades, a different
code path now that this phase's project-override tier sits ahead of it).

**Corrected 2026-09-29** (Decided by: User — see `docs/decisions.md`'s
dated entry and `docs/plans/module-00-platform-foundations-plan.md`'s
Phase 5 correction note): the resolution is no longer "org default,
project override symmetric in either direction" as a single tier. It is
now four tiers — entitlement, the organisation's own hard `enabled` floor
(absolute — no project override can cross it upward, in either direction),
the organisation's own `default_project_enabled` (what a project gets
absent its own override), and a project's own override (symmetric, but
only ever operating *within* the `enabled=True` floor, against
`default_project_enabled` specifically). Every test below that exercised
the original "project override always wins" shape against a hard-disabled
module has been corrected to expect the new floor instead; sub-component
overrides (`test_module_subcomponent_enablement.py`) are unaffected by
this correction.

Projects created through the API get a row per module copied in at
creation, so resolution tests that exercise the "no project row" tier
first call `_drop_snapshot` — modelling a project created before the
module was registered, the only case that still reaches that tier.

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
    ProjectModuleSubComponentEnablement,
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


def _drop_snapshot(db, project_uuid, module_key: str) -> None:
    """Deletes the module/sub-component rows copied into a project at
    creation (`snapshot_project_module_state`), so a test can exercise the
    "no project row" resolution tier — the state of a project created
    before `module_key` was registered."""
    db.query(ProjectModuleEnablement).filter(
        ProjectModuleEnablement.project_id == project_uuid, ProjectModuleEnablement.module_key == module_key,
    ).delete()
    db.query(ProjectModuleSubComponentEnablement).filter(
        ProjectModuleSubComponentEnablement.project_id == project_uuid,
        ProjectModuleSubComponentEnablement.module_key == module_key,
    ).delete()
    db.commit()


# --- is_module_enabled_for_project: all four resolution paths --------------------------


def test_project_enablement_resolution_all_four_paths(client, admin_token, org_id, fake_module):
    project = create_project(client, admin_token, org_id, "Project Whole-Module Enablement Resolution")
    db = SessionLocal()
    try:
        org_uuid = uuid_lib.UUID(org_id)
        project_uuid = uuid_lib.UUID(project["id"])
        _drop_snapshot(db, project_uuid, fake_module)

        # (a) registry default — no org row, no project row.
        assert is_module_enabled_for_project(db, project_uuid, fake_module) is True

        # (b) org's hard `enabled` flag is an absolute floor — overrides
        # the registry default, and no project override (existing or new)
        # can cross it back upward.
        db.add(
            OrganizationModuleEnablement(
                organization_id=org_uuid, module_key=fake_module, enabled=False, default_project_enabled=False,
            )
        )
        db.commit()
        assert is_module_enabled_for_project(db, project_uuid, fake_module) is False

        # (c) **Corrected 2026-09-29**: a project override can no longer
        # cross the hard floor — attempting to widen past `enabled=False`
        # stays False, not the pre-correction "symmetric, wins either
        # direction" behaviour.
        db.add(ProjectModuleEnablement(project_id=project_uuid, module_key=fake_module, enabled=True))
        db.commit()
        assert is_module_enabled_for_project(db, project_uuid, fake_module) is False

        # (d) Once the org's hard floor is True, a project override is
        # symmetric against `default_project_enabled` specifically — this
        # is the corrected feature the reversal exists to support: the org
        # makes the module available but off by default, and a project can
        # still opt in.
        db.query(ProjectModuleEnablement).filter(
            ProjectModuleEnablement.project_id == project_uuid,
            ProjectModuleEnablement.module_key == fake_module,
        ).delete()
        db.query(OrganizationModuleEnablement).filter(
            OrganizationModuleEnablement.organization_id == org_uuid,
            OrganizationModuleEnablement.module_key == fake_module,
        ).delete()
        db.commit()
        db.add(
            OrganizationModuleEnablement(
                organization_id=org_uuid, module_key=fake_module, enabled=True, default_project_enabled=False,
            )
        )
        db.commit()
        # Hard-enabled, but defaulted off for new projects — no project
        # override yet, so this project gets the default (off).
        assert is_module_enabled_for_project(db, project_uuid, fake_module) is False
        # This project opts in — widening past the org's own default is
        # allowed, since the hard floor (`enabled=True`) permits it.
        db.add(ProjectModuleEnablement(project_id=project_uuid, module_key=fake_module, enabled=True))
        db.commit()
        assert is_module_enabled_for_project(db, project_uuid, fake_module) is True

        # Symmetric the other direction too: org default-for-projects on,
        # project override off (narrowing has always been allowed, and
        # still is).
        db.query(ProjectModuleEnablement).filter(
            ProjectModuleEnablement.project_id == project_uuid,
            ProjectModuleEnablement.module_key == fake_module,
        ).delete()
        db.query(OrganizationModuleEnablement).filter(
            OrganizationModuleEnablement.organization_id == org_uuid,
            OrganizationModuleEnablement.module_key == fake_module,
        ).delete()
        db.commit()
        db.add(ProjectModuleEnablement(project_id=project_uuid, module_key=fake_module, enabled=False))
        db.commit()
        assert is_module_enabled_for_project(db, project_uuid, fake_module) is False

        # (e) entitlement is an absolute ceiling — overrides everything,
        # even a project override explicitly set to enabled=True with the
        # org's hard floor otherwise satisfied.
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
        _drop_snapshot(db, project_uuid, fake_module)

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
        _drop_snapshot(db, uuid_lib.UUID(project["id"]), fake_module)
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


def test_require_project_module_enabled_404_when_project_override_enables_over_hard_disabled_org(
    client, admin_token, org_id, fake_module
):
    """**Corrected 2026-09-29**: the org's hard `enabled=False` is now an
    absolute floor — a project override of `enabled=True` can no longer
    cross it, unlike the original 2026-09-28 "symmetric, wins either
    direction" design this test used to assert. The dependency must 404,
    the same as if no override existed at all."""
    project = create_project(client, admin_token, org_id, "Require Project Module Enabled Hard Floor")
    db = SessionLocal()
    try:
        org_uuid = uuid_lib.UUID(org_id)
        project_uuid = uuid_lib.UUID(project["id"])
        _drop_snapshot(db, project_uuid, fake_module)
        db.add(
            OrganizationModuleEnablement(
                organization_id=org_uuid, module_key=fake_module, enabled=False, default_project_enabled=False,
            )
        )
        db.add(ProjectModuleEnablement(project_id=project_uuid, module_key=fake_module, enabled=True))
        db.commit()
        admin_user = _get_admin_user(db)
        dependency = require_project_module_enabled(fake_module)
        with pytest.raises(HTTPException) as exc_info:
            dependency(project_id=project_uuid, request=_FakeRequest(), current_user=admin_user, db=db)
        assert exc_info.value.status_code == 404
    finally:
        db.close()


def test_require_project_module_enabled_passes_when_project_widens_past_org_default_project_enabled_off(
    client, admin_token, org_id, fake_module
):
    """The genuine new capability this correction exists to support: the
    organisation has the module hard-`enabled=True` (available) but
    defaults it off for new projects (`default_project_enabled=False`) —
    a project's own override may still widen past that default and the
    dependency must pass, since the hard floor itself is satisfied."""
    project = create_project(client, admin_token, org_id, "Require Project Module Enabled Opt In")
    db = SessionLocal()
    try:
        org_uuid = uuid_lib.UUID(org_id)
        project_uuid = uuid_lib.UUID(project["id"])
        _drop_snapshot(db, project_uuid, fake_module)
        db.add(
            OrganizationModuleEnablement(
                organization_id=org_uuid, module_key=fake_module, enabled=True, default_project_enabled=False,
            )
        )
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
        _drop_snapshot(db, uuid_lib.UUID(project["id"]), fake_module)
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
    # Copied in at creation.
    assert body["has_project_override"] is True
    assert body["project_override_enabled"] is True

    # Hard-disable at org level — reaches this existing project despite its
    # own copied-in value (the floor).
    resp = client.put(
        f"/api/v1/orgs/{org_id}/modules/{fake_module}", json={"enabled": False}, headers=auth_headers(admin_token),
    )
    assert resp.status_code == 200, resp.text

    resp = client.get(
        f"/api/v1/projects/{project_id}/modules/{fake_module}/enablement", headers=auth_headers(admin_token)
    )
    body = resp.json()
    assert body["effective_enabled"] is False
    assert body["org_hard_enabled"] is False
    assert body["project_override_enabled"] is True

    # **Corrected 2026-09-29**: a project-level override of True can no
    # longer cross the org's own hard `enabled=False` floor — rejected
    # (400), not the pre-correction "wins symmetrically" 200.
    resp = client.put(
        f"/api/v1/projects/{project_id}/modules/{fake_module}/enablement", json={"enabled": True},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 400, resp.text
    assert "disabled for your organisation" in resp.json()["detail"]

    # Narrowing (enabled=False) is always allowed regardless.
    resp = client.put(
        f"/api/v1/projects/{project_id}/modules/{fake_module}/enablement", json={"enabled": False},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["effective_enabled"] is False


def test_project_module_enablement_endpoint_widen_past_org_default_project_enabled_succeeds(
    client, admin_token, org_id, fake_module,
):
    """The organisation makes the module available (`enabled=True`) but
    off by default (`default_project_enabled=False`): a project created
    afterwards starts off, and may still opt in (200, not rejected)."""
    resp = client.put(
        f"/api/v1/orgs/{org_id}/modules/{fake_module}",
        json={"enabled": True, "default_project_enabled": False}, headers=auth_headers(admin_token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["default_project_enabled"] is False
    project_id = create_project(client, admin_token, org_id, "Project Module Enablement Opt In Endpoint")["id"]

    resp = client.get(
        f"/api/v1/projects/{project_id}/modules/{fake_module}/enablement", headers=auth_headers(admin_token)
    )
    body = resp.json()
    assert body["effective_enabled"] is False
    assert body["org_default_enabled"] is False

    resp = client.put(
        f"/api/v1/projects/{project_id}/modules/{fake_module}/enablement", json={"enabled": True},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["effective_enabled"] is True
    assert body["org_default_enabled"] is False
    assert body["project_override_enabled"] is True


def test_org_module_enablement_endpoint_default_project_enabled_semantics(client, admin_token, org_id, fake_module):
    """`default_project_enabled` defaults to match `enabled` on a
    freshly-created row (no explicit value provided), and is left
    untouched on an existing row when omitted from a later `PUT` (only an
    explicit value updates it)."""
    resp = client.get(f"/api/v1/orgs/{org_id}/modules", headers=auth_headers(admin_token))
    by_key = {row["module_key"]: row for row in resp.json()}
    # No row yet — both reflect the registry default.
    assert by_key[fake_module]["enabled"] is True
    assert by_key[fake_module]["default_project_enabled"] is True

    # First-ever explicit choice, `default_project_enabled` omitted — a
    # fresh row initialises it to match `enabled`.
    resp = client.put(
        f"/api/v1/orgs/{org_id}/modules/{fake_module}", json={"enabled": False}, headers=auth_headers(admin_token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["default_project_enabled"] is False

    # Re-enable, still omitting `default_project_enabled` — the *existing*
    # row's own value is left untouched (still False from the step above),
    # not silently reset to match `enabled` again.
    resp = client.put(
        f"/api/v1/orgs/{org_id}/modules/{fake_module}", json={"enabled": True}, headers=auth_headers(admin_token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["default_project_enabled"] is False

    # An explicit value updates it.
    resp = client.put(
        f"/api/v1/orgs/{org_id}/modules/{fake_module}",
        json={"enabled": True, "default_project_enabled": True}, headers=auth_headers(admin_token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["default_project_enabled"] is True


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


# --- GET /projects/{id}/modules (bulk list, added alongside the Project Admin
# --- Modules tab) -------------------------------------------------------------------------


def test_list_project_modules_includes_every_registered_module_with_correct_state(
    client, admin_token, org_id, fake_module,
):
    """The Project Admin Modules tab's own discovery endpoint: every
    registered module appears, including ones this project has no
    override for at all, each with the correct effective/org-default/
    override-provenance state — proven against both an unset module (the
    fake fixture, still at registry default) and one with an actual
    project override set."""
    project = create_project(client, admin_token, org_id, "List Project Modules Project")
    project_id = project["id"]

    resp = client.get(f"/api/v1/projects/{project_id}/modules", headers=auth_headers(admin_token))
    assert resp.status_code == 200, resp.text
    by_key = {row["module_key"]: row for row in resp.json()}
    assert fake_module in by_key
    assert by_key[fake_module]["effective_enabled"] is True
    assert by_key[fake_module]["has_project_override"] is True
    assert by_key[fake_module]["project_override_enabled"] is True
    # A real, already-registered module (Decision Management) also
    # appears, proving this isn't limited to fixture modules.
    assert "decisions" in by_key

    resp = client.put(
        f"/api/v1/projects/{project_id}/modules/{fake_module}/enablement", json={"enabled": False},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 200, resp.text

    resp = client.get(f"/api/v1/projects/{project_id}/modules", headers=auth_headers(admin_token))
    by_key = {row["module_key"]: row for row in resp.json()}
    assert by_key[fake_module]["effective_enabled"] is False
    assert by_key[fake_module]["has_project_override"] is True
    assert by_key[fake_module]["project_override_enabled"] is False


def test_list_project_modules_404_for_unknown_project(client, admin_token):
    resp = client.get(
        f"/api/v1/projects/{uuid_lib.uuid4()}/modules", headers=auth_headers(admin_token),
    )
    assert resp.status_code == 404


# --- Copy-on-create / copy-before-default-change (Decided by: User, 2026-10-04) ----------


def _project_module(client, token, project_id, module_key):
    resp = client.get(f"/api/v1/projects/{project_id}/modules/{module_key}/enablement", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return resp.json()


def _project_sub(client, token, project_id, module_key):
    resp = client.get(f"/api/v1/projects/{project_id}/modules/{module_key}/subcomponents", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return {row["subcomponent_key"]: row for row in resp.json()}[SUBCOMPONENT_KEY]


def test_new_project_copies_org_defaults_at_creation(client, admin_token, org_id, fake_module):
    """A new project gets its own row per module and sub-component holding
    the org's `default_project_enabled` values at that moment."""
    resp = client.put(
        f"/api/v1/orgs/{org_id}/modules/{fake_module}",
        json={"enabled": True, "default_project_enabled": False}, headers=auth_headers(admin_token),
    )
    assert resp.status_code == 200, resp.text
    resp = client.put(
        f"/api/v1/orgs/{org_id}/modules/{fake_module}/subcomponents/{SUBCOMPONENT_KEY}",
        json={"enabled": True, "default_project_enabled": False}, headers=auth_headers(admin_token),
    )
    assert resp.status_code == 200, resp.text
    project_id = create_project(client, admin_token, org_id, "Copy On Create Project")["id"]

    module = _project_module(client, admin_token, project_id, fake_module)
    assert module["has_project_override"] is True
    assert module["project_override_enabled"] is False
    sub = _project_sub(client, admin_token, project_id, fake_module)
    assert sub["has_project_override"] is True
    assert sub["project_override_enabled"] is False


def test_changing_org_default_does_not_change_existing_projects(client, admin_token, org_id, fake_module):
    """Flipping an org default leaves existing projects as they were —
    both one with a copied-in row and one with none (created before the
    module was registered, frozen at the old value first) — while a
    project created afterwards gets the new default."""
    with_row = create_project(client, admin_token, org_id, "Default Change Existing With Row")["id"]
    without_row = create_project(client, admin_token, org_id, "Default Change Existing Without Row")["id"]
    db = SessionLocal()
    try:
        _drop_snapshot(db, uuid_lib.UUID(without_row), fake_module)
    finally:
        db.close()

    resp = client.put(
        f"/api/v1/orgs/{org_id}/modules/{fake_module}",
        json={"enabled": True, "default_project_enabled": False}, headers=auth_headers(admin_token),
    )
    assert resp.status_code == 200, resp.text
    resp = client.put(
        f"/api/v1/orgs/{org_id}/modules/{fake_module}/subcomponents/{SUBCOMPONENT_KEY}",
        json={"enabled": True, "default_project_enabled": False}, headers=auth_headers(admin_token),
    )
    assert resp.status_code == 200, resp.text

    for project_id in (with_row, without_row):
        assert _project_module(client, admin_token, project_id, fake_module)["effective_enabled"] is True
        assert _project_sub(client, admin_token, project_id, fake_module)["effective_enabled"] is True

    new_project = create_project(client, admin_token, org_id, "Default Change New Project")["id"]
    assert _project_module(client, admin_token, new_project, fake_module)["effective_enabled"] is False
    assert _project_sub(client, admin_token, new_project, fake_module)["effective_enabled"] is False


def test_org_hard_off_reaches_existing_projects_and_restores_on_re_enable(client, admin_token, org_id, fake_module):
    """An org-level hard Off (module or sub-component) turns it off for
    every existing project at once; turning it back on restores each
    project's own value."""
    project_id = create_project(client, admin_token, org_id, "Hard Off Existing Project")["id"]

    resp = client.put(
        f"/api/v1/orgs/{org_id}/modules/{fake_module}/subcomponents/{SUBCOMPONENT_KEY}",
        json={"enabled": False, "default_project_enabled": True}, headers=auth_headers(admin_token),
    )
    assert resp.status_code == 200, resp.text
    sub = _project_sub(client, admin_token, project_id, fake_module)
    assert sub["effective_enabled"] is False
    assert sub["org_hard_enabled"] is False
    assert sub["project_override_enabled"] is True

    resp = client.put(
        f"/api/v1/orgs/{org_id}/modules/{fake_module}",
        json={"enabled": False, "default_project_enabled": True}, headers=auth_headers(admin_token),
    )
    assert resp.status_code == 200, resp.text
    assert _project_module(client, admin_token, project_id, fake_module)["effective_enabled"] is False

    for url in (
        f"/api/v1/orgs/{org_id}/modules/{fake_module}",
        f"/api/v1/orgs/{org_id}/modules/{fake_module}/subcomponents/{SUBCOMPONENT_KEY}",
    ):
        resp = client.put(url, json={"enabled": True}, headers=auth_headers(admin_token))
        assert resp.status_code == 200, resp.text
    assert _project_module(client, admin_token, project_id, fake_module)["effective_enabled"] is True
    assert _project_sub(client, admin_token, project_id, fake_module)["effective_enabled"] is True


def test_project_cannot_enable_subcomponent_the_org_hard_disabled(client, admin_token, org_id, fake_module):
    """Sub-components share the module hard floor: a project may not turn
    on a sub-component its organisation has turned off (400); turning it
    off is always allowed."""
    project_id = create_project(client, admin_token, org_id, "Sub Hard Floor Project")["id"]
    resp = client.put(
        f"/api/v1/orgs/{org_id}/modules/{fake_module}/subcomponents/{SUBCOMPONENT_KEY}",
        json={"enabled": False}, headers=auth_headers(admin_token),
    )
    assert resp.status_code == 200, resp.text

    url = f"/api/v1/projects/{project_id}/modules/{fake_module}/subcomponents/{SUBCOMPONENT_KEY}"
    resp = client.put(url, json={"enabled": True}, headers=auth_headers(admin_token))
    assert resp.status_code == 400, resp.text
    resp = client.put(url, json={"enabled": False}, headers=auth_headers(admin_token))
    assert resp.status_code == 200, resp.text


def test_project_created_while_module_off_gets_default_when_org_turns_it_on(client, admin_token, org_id, fake_module):
    """Nothing is copied while a module is unavailable (hard-off), so a
    project created then picks up the org's default once the module is
    turned on — rather than being stuck with a stale Off. Its value is
    then frozen like any other project's on the next default change."""
    resp = client.put(
        f"/api/v1/orgs/{org_id}/modules/{fake_module}", json={"enabled": False}, headers=auth_headers(admin_token),
    )
    assert resp.status_code == 200, resp.text
    project_id = create_project(client, admin_token, org_id, "Created While Module Off")["id"]
    assert _project_module(client, admin_token, project_id, fake_module)["has_project_override"] is False

    resp = client.put(
        f"/api/v1/orgs/{org_id}/modules/{fake_module}",
        json={"enabled": True, "default_project_enabled": True}, headers=auth_headers(admin_token),
    )
    assert resp.status_code == 200, resp.text
    assert _project_module(client, admin_token, project_id, fake_module)["effective_enabled"] is True

    resp = client.put(
        f"/api/v1/orgs/{org_id}/modules/{fake_module}",
        json={"enabled": True, "default_project_enabled": False}, headers=auth_headers(admin_token),
    )
    assert resp.status_code == 200, resp.text
    assert _project_module(client, admin_token, project_id, fake_module)["effective_enabled"] is True
