"""Tests for `ModuleSubComponentDefinition.organization_only`: a sub-component owned by the organisation has no
project-level state, so the project API neither lists nor accepts it, the resolver ignores any stored project row,
no project row is created for it, and a template copy skips it. The organisation API is unchanged.

Uses a fake module (as `test_module_subcomponent_enablement.py` does), plus one check against the real registry that
the Product Feedback request inbox is declared organisation-only."""

import uuid as uuid_lib

import pytest

from app.database import SessionLocal
from app.models.module import ProjectModuleEnablement, ProjectModuleSubComponentEnablement
from app.modules import registry as module_registry
from app.modules.registry import (
    ModuleDefinition,
    ModuleSubComponentDefinition,
    build_registry,
    get_frontend_manifest,
    get_module_registry,
    is_module_subcomponent_enabled,
    is_org_module_subcomponent_enabled,
)
from tests.conftest import auth_headers, create_project

FAKE_MODULE_KEY = "fake_org_only_test_module"
SHARED_KEY = "shared"
ORG_ONLY_KEY = "inbox"


@pytest.fixture
def fake_module():
    """Registers a fake module with one project-level and one organisation-only sub-component for one test."""
    module_registry.INSTALLED_MODULES.append(ModuleDefinition(
        key=FAKE_MODULE_KEY, name="Fake Org-Only Test Module", description="Fixture for organisation-only tests.",
        version="0.0.1", default_enabled=True, implemented=False, get_router=lambda: None,
        sub_components=(
            ModuleSubComponentDefinition(key=SHARED_KEY, name="Shared", default_enabled=True),
            ModuleSubComponentDefinition(key=ORG_ONLY_KEY, name="Inbox", default_enabled=True, organization_only=True),
        ),
    ))
    build_registry(force=True)
    yield FAKE_MODULE_KEY
    module_registry.INSTALLED_MODULES[:] = [m for m in module_registry.INSTALLED_MODULES if m.key != FAKE_MODULE_KEY]
    build_registry(force=True)


def _project_rows(project_id: str) -> dict[str, bool]:
    db = SessionLocal()
    try:
        return {
            row.subcomponent_key: row.enabled
            for row in db.query(ProjectModuleSubComponentEnablement).filter(
                ProjectModuleSubComponentEnablement.project_id == uuid_lib.UUID(project_id),
                ProjectModuleSubComponentEnablement.module_key == FAKE_MODULE_KEY,
            )
        }
    finally:
        db.close()


def test_project_list_omits_organization_only_but_keeps_the_rest(client, admin_token, org_id, fake_module):
    project_id = create_project(client, admin_token, org_id, "Org-only list project")["id"]
    resp = client.get(f"/api/v1/projects/{project_id}/modules/{fake_module}/subcomponents", headers=auth_headers(admin_token))
    assert resp.status_code == 200, resp.text
    assert [row["subcomponent_key"] for row in resp.json()] == [SHARED_KEY]


def test_project_put_for_organization_only_is_404_and_stores_nothing(client, admin_token, org_id, fake_module):
    project_id = create_project(client, admin_token, org_id, "Org-only put project")["id"]
    for enabled in (True, False):
        resp = client.put(
            f"/api/v1/projects/{project_id}/modules/{fake_module}/subcomponents/{ORG_ONLY_KEY}",
            json={"enabled": enabled}, headers=auth_headers(admin_token),
        )
        assert resp.status_code == 404, resp.text
    assert ORG_ONLY_KEY not in _project_rows(project_id)
    # The project-level sibling is still writable.
    resp = client.put(
        f"/api/v1/projects/{project_id}/modules/{fake_module}/subcomponents/{SHARED_KEY}",
        json={"enabled": False}, headers=auth_headers(admin_token),
    )
    assert resp.status_code == 200, resp.text


def test_organization_list_and_put_are_unchanged(client, admin_token, org_id, fake_module):
    url = f"/api/v1/orgs/{org_id}/modules/{fake_module}/subcomponents"
    resp = client.get(url, headers=auth_headers(admin_token))
    assert {row["subcomponent_key"] for row in resp.json()} == {SHARED_KEY, ORG_ONLY_KEY}
    resp = client.put(f"{url}/{ORG_ONLY_KEY}", json={"enabled": False}, headers=auth_headers(admin_token))
    assert resp.status_code == 200, resp.text
    assert resp.json()["enabled"] is False


def test_new_project_gets_no_row_for_organization_only(client, admin_token, org_id, fake_module):
    project_id = create_project(client, admin_token, org_id, "Org-only snapshot project")["id"]
    rows = _project_rows(project_id)
    assert SHARED_KEY in rows
    assert ORG_ONLY_KEY not in rows


def test_resolver_follows_the_organisation_and_ignores_a_stale_project_row(client, admin_token, org_id, fake_module):
    project_id = create_project(client, admin_token, org_id, "Org-only resolver project")["id"]
    db = SessionLocal()
    try:
        project_uuid = uuid_lib.UUID(project_id)
        # A row an earlier version could have stored: it must neither disable nor enable anything.
        db.add(ProjectModuleSubComponentEnablement(
            project_id=project_uuid, module_key=FAKE_MODULE_KEY, subcomponent_key=ORG_ONLY_KEY, enabled=False,
        ))
        db.commit()
        assert is_module_subcomponent_enabled(db, project_uuid, FAKE_MODULE_KEY, ORG_ONLY_KEY) is True
        assert is_org_module_subcomponent_enabled(db, uuid_lib.UUID(org_id), FAKE_MODULE_KEY, ORG_ONLY_KEY) is True
    finally:
        db.close()

    resp = client.put(
        f"/api/v1/orgs/{org_id}/modules/{FAKE_MODULE_KEY}/subcomponents/{ORG_ONLY_KEY}",
        json={"enabled": False}, headers=auth_headers(admin_token),
    )
    assert resp.status_code == 200, resp.text
    db = SessionLocal()
    try:
        assert is_module_subcomponent_enabled(db, uuid_lib.UUID(project_id), FAKE_MODULE_KEY, ORG_ONLY_KEY) is False
    finally:
        db.close()


def test_template_copy_skips_organization_only_rows(client, admin_token, org_id, fake_module):
    from app.models.project import Project
    from app.services.template_content import copy_module_enablement

    template_id = create_project(client, admin_token, org_id, "Org-only template project")["id"]
    target_id = create_project(client, admin_token, org_id, "Org-only template target")["id"]
    db = SessionLocal()
    try:
        db.add(ProjectModuleSubComponentEnablement(
            project_id=uuid_lib.UUID(template_id), module_key=FAKE_MODULE_KEY, subcomponent_key=ORG_ONLY_KEY, enabled=True,
        ))
        db.commit()
        # Clear what creation already snapshotted so the copy is the only writer.
        for model in (ProjectModuleEnablement, ProjectModuleSubComponentEnablement):
            db.query(model).filter(model.project_id == uuid_lib.UUID(target_id)).delete()
        db.commit()
        copy_module_enablement(db, db.get(Project, uuid_lib.UUID(template_id)), db.get(Project, uuid_lib.UUID(target_id)))
        db.commit()
    finally:
        db.close()
    assert ORG_ONLY_KEY not in _project_rows(target_id)


def test_real_inbox_is_organization_only_and_never_gated_at_project_level():
    """The Product Feedback inbox is declared organisation-only, and no navigation entry or report in any module
    gates on an organisation-only key at project level (it would be a gate no project can change)."""
    registry = get_module_registry()
    org_only = {
        (key, sub.key) for key, definition in registry.items() for sub in definition.sub_components if sub.organization_only
    }
    assert ("product_feedback", "organization_requests") in org_only

    for key, definition in registry.items():
        manifest = get_frontend_manifest(key)
        if manifest is not None:
            gates = {manifest.nav_sub_component, *manifest.nav_sub_components_any}
            for entry in manifest.additional_nav_entries:
                gates |= {entry.sub_component, *entry.sub_components_any}
            assert not {(key, gate) for gate in gates if gate} & org_only
        for report in definition.reports:
            referenced = {report.subcomponent, *report.any_subcomponents}
            assert not {(key, gate) for gate in referenced if gate} & org_only, report.key
