"""Tests for server-wide module availability: the `ServerModuleDefault` tier in the resolution
chain (registry < server default < organisation row), the `/system/module-defaults` endpoints
and their audit trail, "apply to all organisations", fresh-install seeding (and its absence on
an upgrade), the per-organisation view that names the deciding tier, and hiding modules an
administrator cannot use (non-entitled modules from organisation admins, organisation-disabled
modules and sub-components from project admins)."""

import uuid as uuid_lib

import pytest
from sqlalchemy import delete, select

from app.config import get_settings
from app.database import SessionLocal
from app.models.audit import AuditEvent
from app.models.module import OrganizationModuleEnablement, ProjectModuleEnablement, ServerModuleDefault
from app.models.organization import ServerSettings
from app.modules.registry import (
    get_module_registry,
    is_module_enabled,
    is_module_enabled_for_project,
    resolve_default_project_enabled,
)
from app.services.module_defaults import seed_fresh_install_defaults
from tests.conftest import auth_headers, create_org_admin_in, create_org_user, create_project, login

# An opt-in module in the registry (`default_enabled=False`): the interesting one for defaults.
OPT_IN = "decisions"


def _put_default(client, token, module_key, org_enabled, project_default_enabled):
    return client.put(
        f"/api/v1/system/module-defaults/{module_key}",
        json={"org_enabled": org_enabled, "project_default_enabled": project_default_enabled},
        headers=auth_headers(token),
    )


def _org_module(client, token, org_id, module_key):
    resp = client.get(f"/api/v1/orgs/{org_id}/modules", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return {m["module_key"]: m for m in resp.json()}.get(module_key)


# --- resolution chain ------------------------------------------------------------------


def test_resolution_registry_then_server_default_then_org_row(client, admin_token, org_id):
    org_uuid = uuid_lib.UUID(org_id)
    db = SessionLocal()
    try:
        # No server default, no org row: the registry's own opt-in default applies.
        assert is_module_enabled(db, org_uuid, OPT_IN) is False
        assert resolve_default_project_enabled(db, org_uuid, OPT_IN) is False

        db.add(ServerModuleDefault(module_key=OPT_IN, org_enabled=True, project_default_enabled=True))
        db.commit()
        assert is_module_enabled(db, org_uuid, OPT_IN) is True
        assert resolve_default_project_enabled(db, org_uuid, OPT_IN) is True

        # An organisation's own row beats the server default, in either direction.
        db.add(OrganizationModuleEnablement(
            organization_id=org_uuid, module_key=OPT_IN, enabled=False, default_project_enabled=False,
        ))
        db.commit()
        assert is_module_enabled(db, org_uuid, OPT_IN) is False
        assert resolve_default_project_enabled(db, org_uuid, OPT_IN) is False
    finally:
        db.close()


def test_server_default_off_beats_registry_default_on(client, admin_token, org_id):
    """A server default can also switch off a module the registry has on (Compliance)."""
    assert _put_default(client, admin_token, "compliance", False, False).status_code == 200
    db = SessionLocal()
    try:
        assert is_module_enabled(db, uuid_lib.UUID(org_id), "compliance") is False
    finally:
        db.close()


def test_closed_entitlement_policy_still_gates_a_server_default(client, admin_token, org_id):
    assert _put_default(client, admin_token, OPT_IN, True, True).status_code == 200
    resp = client.put(
        f"/api/v1/system/orgs/{org_id}/module-entitlements/{OPT_IN}", json={"entitled": False},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 200
    db = SessionLocal()
    try:
        assert is_module_enabled(db, uuid_lib.UUID(org_id), OPT_IN) is False
    finally:
        db.close()


# --- endpoints, access control and audit -----------------------------------------------


def test_list_and_update_server_module_defaults(client, admin_token):
    resp = client.get("/api/v1/system/module-defaults", headers=auth_headers(admin_token))
    assert resp.status_code == 200, resp.text
    by_key = {row["module_key"]: row for row in resp.json()}
    assert set(by_key) == set(get_module_registry())
    assert by_key[OPT_IN]["org_enabled"] is False
    assert by_key[OPT_IN]["has_override"] is False

    resp = _put_default(client, admin_token, OPT_IN, True, False)
    assert resp.status_code == 200, resp.text
    assert (resp.json()["org_enabled"], resp.json()["project_default_enabled"], resp.json()["has_override"]) == (
        True, False, True,
    )
    by_key = {r["module_key"]: r for r in client.get("/api/v1/system/module-defaults", headers=auth_headers(admin_token)).json()}
    assert (by_key[OPT_IN]["org_enabled"], by_key[OPT_IN]["project_default_enabled"]) == (True, False)

    db = SessionLocal()
    try:
        event = db.scalar(select(AuditEvent).where(AuditEvent.action == "module.server_default_updated"))
        assert event is not None and event.entity_id == OPT_IN
        assert event.detail == {"module_key": OPT_IN, "org_enabled": True, "project_default_enabled": False}
    finally:
        db.close()


def test_update_default_for_unknown_module_is_404(client, admin_token):
    assert _put_default(client, admin_token, "no_such_module", True, True).status_code == 404


def test_server_module_defaults_require_a_server_role(client, admin_token, org_id):
    create_org_user(client, admin_token, org_id, "plain-member@example.com")
    token = login(client, "plain-member@example.com", "Password123!")
    assert client.get("/api/v1/system/module-defaults", headers=auth_headers(token)).status_code == 403
    assert _put_default(client, token, OPT_IN, True, True).status_code == 403
    resp = client.post("/api/v1/system/module-defaults/apply", json={}, headers=auth_headers(token))
    assert resp.status_code == 403


def test_changing_project_default_freezes_existing_projects(client, admin_token, org_id):
    """Only projects created after the change read the new project default."""
    assert _put_default(client, admin_token, OPT_IN, True, False).status_code == 200
    existing = create_project(client, admin_token, org_id, "Before Default Change")
    assert _put_default(client, admin_token, OPT_IN, True, True).status_code == 200
    created_after = create_project(client, admin_token, org_id, "After Default Change")
    db = SessionLocal()
    try:
        assert is_module_enabled_for_project(db, uuid_lib.UUID(existing["id"]), OPT_IN) is False
        assert is_module_enabled_for_project(db, uuid_lib.UUID(created_after["id"]), OPT_IN) is True
    finally:
        db.close()


# --- apply to all organisations --------------------------------------------------------


def test_apply_replaces_org_choices_skips_non_entitled_and_keeps_projects(client, admin_token, org_id):
    other_org, _ = create_org_admin_in(client, admin_token, "Apply Target Org")
    # org_id has the module available but off for new projects, and a project created under that.
    assert client.put(
        f"/api/v1/orgs/{org_id}/modules/{OPT_IN}", json={"enabled": True, "default_project_enabled": False},
        headers=auth_headers(admin_token),
    ).status_code == 200
    project = create_project(client, admin_token, org_id, "Apply Existing Project")
    # The other organisation is not entitled to the module.
    assert client.put(
        f"/api/v1/system/orgs/{other_org['id']}/module-entitlements/{OPT_IN}", json={"entitled": False},
        headers=auth_headers(admin_token),
    ).status_code == 200
    assert _put_default(client, admin_token, OPT_IN, True, True).status_code == 200

    resp = client.post(
        "/api/v1/system/module-defaults/apply", json={"module_key": OPT_IN}, headers=auth_headers(admin_token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["rows_written"] >= 1

    db = SessionLocal()
    try:
        row = db.scalar(select(OrganizationModuleEnablement).where(
            OrganizationModuleEnablement.organization_id == uuid_lib.UUID(org_id),
            OrganizationModuleEnablement.module_key == OPT_IN,
        ))
        assert (row.enabled, row.default_project_enabled) == (True, True)
        assert db.scalar(select(OrganizationModuleEnablement).where(
            OrganizationModuleEnablement.organization_id == uuid_lib.UUID(other_org["id"]),
            OrganizationModuleEnablement.module_key == OPT_IN,
        )) is None
        # The project predates the apply, so it keeps the default it had (off) rather than flipping on.
        assert is_module_enabled_for_project(db, uuid_lib.UUID(project["id"]), OPT_IN) is False
        event = db.scalar(select(AuditEvent).where(AuditEvent.action == "module.server_defaults_applied"))
        assert event is not None and event.detail["module_key"] == OPT_IN
    finally:
        db.close()


def test_apply_is_idempotent_and_unknown_module_is_404(client, admin_token):
    assert _put_default(client, admin_token, OPT_IN, True, True).status_code == 200
    first = client.post("/api/v1/system/module-defaults/apply", json={"module_key": OPT_IN}, headers=auth_headers(admin_token))
    second = client.post("/api/v1/system/module-defaults/apply", json={"module_key": OPT_IN}, headers=auth_headers(admin_token))
    assert first.json()["rows_written"] >= 1
    assert second.json() == {"organizations_changed": 0, "rows_written": 0}
    resp = client.post("/api/v1/system/module-defaults/apply", json={"module_key": "nope"}, headers=auth_headers(admin_token))
    assert resp.status_code == 404


# --- fresh-install seeding -------------------------------------------------------------


@pytest.fixture
def no_server_settings():
    """Models a fresh database: no `ServerSettings` row and no server module defaults."""
    db = SessionLocal()
    try:
        db.execute(delete(ServerModuleDefault))
        db.execute(delete(ServerSettings))
        db.commit()
    finally:
        db.close()


def test_fresh_install_is_seeded_all_on_exactly_once(client, no_server_settings, monkeypatch):
    monkeypatch.setattr(get_settings(), "modules_default_available", True)
    db = SessionLocal()
    try:
        assert seed_fresh_install_defaults(db) is True
        rows = list(db.scalars(select(ServerModuleDefault)))
        assert {r.module_key for r in rows} == set(get_module_registry())
        assert all(r.org_enabled and r.project_default_enabled for r in rows)
        # The settings row now exists, so a restart never reseeds over an administrator's change.
        assert seed_fresh_install_defaults(db) is False
    finally:
        db.close()


def test_upgrade_seeds_nothing(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "modules_default_available", True)
    db = SessionLocal()
    try:
        from app.services.branding import get_server_settings

        get_server_settings(db)
        db.execute(delete(ServerModuleDefault))
        db.commit()
        assert seed_fresh_install_defaults(db) is False
        assert db.scalar(select(ServerModuleDefault.id)) is None
    finally:
        db.close()


def test_seeding_can_be_switched_off(client, no_server_settings, monkeypatch):
    monkeypatch.setattr(get_settings(), "modules_default_available", False)
    db = SessionLocal()
    try:
        assert seed_fresh_install_defaults(db) is False
        assert db.scalar(select(ServerModuleDefault.id)) is None
    finally:
        db.close()


# --- per-organisation view -------------------------------------------------------------


def test_org_entitlement_view_names_the_deciding_tier(client, admin_token, org_id):
    def view():
        rows = client.get(f"/api/v1/system/orgs/{org_id}/module-entitlements", headers=auth_headers(admin_token)).json()
        return {r["module_key"]: r for r in rows}[OPT_IN]

    assert (view()["enabled"], view()["enabled_source"]) == (False, "registry")
    assert _put_default(client, admin_token, OPT_IN, True, True).status_code == 200
    assert (view()["enabled"], view()["enabled_source"]) == (True, "server_default")
    assert client.put(
        f"/api/v1/orgs/{org_id}/modules/{OPT_IN}", json={"enabled": False}, headers=auth_headers(admin_token),
    ).status_code == 200
    assert (view()["enabled"], view()["enabled_source"]) == (False, "organization")
    resp = client.put(
        f"/api/v1/system/orgs/{org_id}/module-entitlements/{OPT_IN}", json={"entitled": False},
        headers=auth_headers(admin_token),
    )
    assert resp.json()["entitled"] is False and resp.json()["enabled"] is False


# --- hiding ----------------------------------------------------------------------------


def test_non_entitled_module_is_hidden_from_org_admin_but_not_server_admin(client, admin_token):
    org, org_admin_token = create_org_admin_in(client, admin_token, "Hiding Org")
    assert client.put(
        f"/api/v1/system/orgs/{org['id']}/module-entitlements/{OPT_IN}", json={"entitled": False},
        headers=auth_headers(admin_token),
    ).status_code == 200
    assert _org_module(client, org_admin_token, org["id"], OPT_IN) is None
    assert _org_module(client, org_admin_token, org["id"], "compliance") is not None

    # A server administrator who is also an admin of the organisation keeps the full view.
    create_org_user(client, admin_token, org["id"], "hiding-server-admin@example.com", role="org_admin")
    resp = client.get("/api/v1/system/modules", headers=auth_headers(admin_token))
    assert OPT_IN in {m["module_key"] for m in resp.json()}


def test_org_disabled_module_is_hidden_from_project_admin(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id, "Hide Disabled Module")

    def project_modules():
        resp = client.get(f"/api/v1/projects/{project['id']}/modules", headers=auth_headers(admin_token))
        assert resp.status_code == 200, resp.text
        return {m["module_key"] for m in resp.json()}

    assert "compliance" in project_modules()
    assert client.put(
        f"/api/v1/orgs/{org_id}/modules/compliance", json={"enabled": False}, headers=auth_headers(admin_token),
    ).status_code == 200
    assert "compliance" not in project_modules()
    # The project's override row is kept, so the module returns with its state on re-enable.
    db = SessionLocal()
    try:
        assert db.scalar(select(ProjectModuleEnablement.id).where(
            ProjectModuleEnablement.project_id == uuid_lib.UUID(project["id"]),
            ProjectModuleEnablement.module_key == "compliance",
        )) is not None
    finally:
        db.close()
    assert client.put(
        f"/api/v1/orgs/{org_id}/modules/compliance", json={"enabled": True}, headers=auth_headers(admin_token),
    ).status_code == 200
    assert "compliance" in project_modules()


def test_org_disabled_subcomponents_are_hidden_from_project_admin(client, admin_token, org_id):
    module_key = "context_strategy"
    assert client.put(
        f"/api/v1/orgs/{org_id}/modules/{module_key}", json={"enabled": True}, headers=auth_headers(admin_token),
    ).status_code == 200
    project = create_project(client, admin_token, org_id, "Hide Disabled Subcomponent")
    url = f"/api/v1/projects/{project['id']}/modules/{module_key}/subcomponents"
    subs = client.get(url, headers=auth_headers(admin_token)).json()
    assert len(subs) > 1
    hidden_key = subs[0]["subcomponent_key"]
    assert client.put(
        f"/api/v1/orgs/{org_id}/modules/{module_key}/subcomponents/{hidden_key}", json={"enabled": False},
        headers=auth_headers(admin_token),
    ).status_code == 200
    remaining = {s["subcomponent_key"] for s in client.get(url, headers=auth_headers(admin_token)).json()}
    assert hidden_key not in remaining and remaining

    assert client.put(
        f"/api/v1/orgs/{org_id}/modules/{module_key}", json={"enabled": False}, headers=auth_headers(admin_token),
    ).status_code == 200
    assert client.get(url, headers=auth_headers(admin_token)).json() == []
