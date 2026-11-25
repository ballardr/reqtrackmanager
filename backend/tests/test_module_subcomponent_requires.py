"""Tests for `ModuleSubComponentDefinition.requires`: a sub-component is not in effect while a sub-component it requires
is not, at the project and organisation tiers, with its own switch and rows kept and the settings endpoints naming what
it is waiting on. Also pins the `ModuleDefinition` validation of a `requires` declaration.

Uses a fake module (as `test_module_subcomponent_enablement.py` does) with a chain `leaf` -> `middle` -> `base` and an
independent `solo`, so the suite does not depend on a content module."""

import uuid as uuid_lib

import pytest

from app.database import SessionLocal
from app.models.module import (
    OrganizationModuleEnablement,
    OrganizationModuleSubComponentDefault,
    ProjectModuleSubComponentEnablement,
)
from app.modules import registry as module_registry
from app.modules.registry import (
    ModuleDefinition,
    ModuleSubComponentDefinition,
    build_registry,
    is_module_subcomponent_enabled,
    is_org_module_subcomponent_enabled,
    unmet_org_subcomponent_requirements,
    unmet_subcomponent_requirements,
)
from tests.conftest import auth_headers, create_project

KEY = "fake_requires_test_module"


def _definition(**overrides) -> ModuleDefinition:
    defaults = dict(
        key=KEY, name="Fake Requires Module", description="Fixture for the requires tests.", version="0.0.1",
        default_enabled=True, implemented=False, get_router=lambda: None,
        sub_components=(
            ModuleSubComponentDefinition(key="base", name="Base"),
            ModuleSubComponentDefinition(key="middle", name="Middle", requires=("base",)),
            ModuleSubComponentDefinition(key="leaf", name="Leaf", requires=("middle",)),
            ModuleSubComponentDefinition(key="solo", name="Solo"),
        ),
    )
    defaults.update(overrides)
    return ModuleDefinition(**defaults)


@pytest.fixture
def fake_module():
    module_registry.INSTALLED_MODULES.append(_definition())
    build_registry(force=True)
    yield KEY
    module_registry.INSTALLED_MODULES[:] = [m for m in module_registry.INSTALLED_MODULES if m.key != KEY]
    build_registry(force=True)


def _org_off(db, org_uuid, sub_key: str) -> None:
    db.add(
        OrganizationModuleSubComponentDefault(
            organization_id=org_uuid, module_key=KEY, subcomponent_key=sub_key, enabled=False,
            default_project_enabled=False,
        )
    )
    db.commit()


# --- declaration validation ------------------------------------------------------------


@pytest.mark.parametrize(
    ("subs", "message"),
    [
        ((ModuleSubComponentDefinition(key="a", name="A", requires=("a",)),), "cannot require itself"),
        ((ModuleSubComponentDefinition(key="a", name="A", requires=("missing",)),), "unknown"),
        (
            (
                ModuleSubComponentDefinition(key="a", name="A", requires=("b",)),
                ModuleSubComponentDefinition(key="b", name="B", requires=("c",)),
                ModuleSubComponentDefinition(key="c", name="C", requires=("a",)),
            ),
            "cycle",
        ),
    ],
)
def test_invalid_requires_declaration_is_rejected(subs, message):
    with pytest.raises(ValueError, match=message):
        _definition(sub_components=subs)


def test_valid_requires_declaration_is_accepted():
    definition = _definition()
    assert {s.key: s.requires for s in definition.sub_components}["leaf"] == ("middle",)


# --- project tier ----------------------------------------------------------------------


def test_project_requirement_off_makes_dependent_ineffective_and_keeps_its_row(client, admin_token, org_id, fake_module):
    project = create_project(client, admin_token, org_id, "Requires Project Tier")
    project_uuid = uuid_lib.UUID(project["id"])
    db = SessionLocal()
    try:
        db.query(ProjectModuleSubComponentEnablement).filter_by(project_id=project_uuid).delete()
        db.commit()
        assert is_module_subcomponent_enabled(db, project_uuid, KEY, "leaf") is True

        db.add(ProjectModuleSubComponentEnablement(project_id=project_uuid, module_key=KEY, subcomponent_key="leaf", enabled=True))
        db.add(ProjectModuleSubComponentEnablement(project_id=project_uuid, module_key=KEY, subcomponent_key="base", enabled=False))
        db.commit()

        assert is_module_subcomponent_enabled(db, project_uuid, KEY, "base") is False
        # The chain cascades: `middle` waits on `base`, `leaf` waits on `middle`.
        assert is_module_subcomponent_enabled(db, project_uuid, KEY, "middle") is False
        assert is_module_subcomponent_enabled(db, project_uuid, KEY, "leaf") is False
        assert [s.key for s in unmet_subcomponent_requirements(db, project_uuid, KEY, "leaf")] == ["middle"]
        # An unrelated sibling is unaffected, and the dependent's own row is untouched.
        assert is_module_subcomponent_enabled(db, project_uuid, KEY, "solo") is True
        assert db.query(ProjectModuleSubComponentEnablement).filter_by(
            project_id=project_uuid, subcomponent_key="leaf",
        ).one().enabled is True

        # Switching the requirement back on restores the dependents with no further change.
        db.query(ProjectModuleSubComponentEnablement).filter_by(
            project_id=project_uuid, subcomponent_key="base",
        ).update({"enabled": True})
        db.commit()
        assert is_module_subcomponent_enabled(db, project_uuid, KEY, "leaf") is True
        assert unmet_subcomponent_requirements(db, project_uuid, KEY, "leaf") == []
    finally:
        db.close()


def test_project_requirement_floored_off_by_organisation_blocks_dependent(client, admin_token, org_id, fake_module):
    project = create_project(client, admin_token, org_id, "Requires Org Floor")
    project_uuid = uuid_lib.UUID(project["id"])
    db = SessionLocal()
    try:
        _org_off(db, uuid_lib.UUID(org_id), "base")
        assert is_module_subcomponent_enabled(db, project_uuid, KEY, "middle") is False
        assert is_module_subcomponent_enabled(db, project_uuid, KEY, "solo") is True
    finally:
        db.close()


def test_whole_module_off_reports_no_unmet_requirement(client, admin_token, org_id, fake_module):
    project = create_project(client, admin_token, org_id, "Requires Module Off")
    project_uuid = uuid_lib.UUID(project["id"])
    db = SessionLocal()
    try:
        db.add(OrganizationModuleEnablement(organization_id=uuid_lib.UUID(org_id), module_key=KEY, enabled=False, default_project_enabled=False))
        db.commit()
        assert is_module_subcomponent_enabled(db, project_uuid, KEY, "middle") is False
        assert unmet_subcomponent_requirements(db, project_uuid, KEY, "middle") == []
    finally:
        db.close()


# --- organisation tier -----------------------------------------------------------------


def test_org_requirement_off_makes_dependent_ineffective(client, admin_token, org_id, fake_module):
    db = SessionLocal()
    try:
        org_uuid = uuid_lib.UUID(org_id)
        assert is_org_module_subcomponent_enabled(db, org_uuid, KEY, "leaf") is True
        _org_off(db, org_uuid, "base")
        assert is_org_module_subcomponent_enabled(db, org_uuid, KEY, "middle") is False
        assert is_org_module_subcomponent_enabled(db, org_uuid, KEY, "leaf") is False
        assert [s.key for s in unmet_org_subcomponent_requirements(db, org_uuid, KEY, "middle")] == ["base"]
        assert is_org_module_subcomponent_enabled(db, org_uuid, KEY, "solo") is True
    finally:
        db.close()


# --- endpoints -------------------------------------------------------------------------


def test_org_endpoint_names_what_a_dependent_is_waiting_on(client, admin_token, org_id, fake_module):
    headers = auth_headers(admin_token)
    url = f"/api/v1/orgs/{org_id}/modules/{KEY}/subcomponents"
    assert {r["subcomponent_key"]: r["blocked_by"] for r in client.get(url, headers=headers).json()} == {
        "base": [], "middle": [], "leaf": [], "solo": [],
    }

    resp = client.put(f"{url}/base", json={"enabled": False}, headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["blocked_by"] == []

    rows = {r["subcomponent_key"]: r for r in client.get(url, headers=headers).json()}
    assert rows["middle"]["blocked_by"] == ["Base"]
    assert rows["leaf"]["blocked_by"] == ["Middle"]
    # The dependent's own switch still reads as set: the dependency makes it ineffective, it never rewrites it.
    assert rows["middle"]["enabled"] is True
    assert rows["solo"]["blocked_by"] == []

    resp = client.put(f"{url}/middle", json={"enabled": True}, headers=headers)
    assert resp.json()["blocked_by"] == ["Base"]


def test_project_endpoint_names_what_a_dependent_is_waiting_on(client, admin_token, org_id, fake_module):
    headers = auth_headers(admin_token)
    project_id = create_project(client, admin_token, org_id, "Requires Endpoint Project")["id"]
    url = f"/api/v1/projects/{project_id}/modules/{KEY}/subcomponents"

    resp = client.put(f"{url}/base", json={"enabled": False}, headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["effective_enabled"] is False
    assert resp.json()["blocked_by"] == []

    rows = {r["subcomponent_key"]: r for r in client.get(url, headers=headers).json()}
    assert rows["middle"]["effective_enabled"] is False
    assert rows["middle"]["blocked_by"] == ["Base"]
    assert rows["leaf"]["blocked_by"] == ["Middle"]
    assert rows["solo"]["effective_enabled"] is True

    # An administrator may still set the dependent: the value is kept and takes effect once its requirement is on.
    resp = client.put(f"{url}/leaf", json={"enabled": True}, headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["effective_enabled"] is False
    assert resp.json()["blocked_by"] == ["Middle"]

    client.put(f"{url}/base", json={"enabled": True}, headers=headers)
    rows = {r["subcomponent_key"]: r for r in client.get(url, headers=headers).json()}
    assert rows["leaf"]["effective_enabled"] is True
    assert rows["leaf"]["blocked_by"] == []


def test_enabled_modules_lists_a_blocked_dependent_as_disabled(client, admin_token, org_id, fake_module):
    headers = auth_headers(admin_token)
    client.put(f"/api/v1/orgs/{org_id}/modules/{KEY}/subcomponents/base", json={"enabled": False}, headers=headers)
    listing = {m["module_key"]: m for m in client.get(f"/api/v1/orgs/{org_id}/enabled-modules", headers=headers).json()}
    assert set(listing[KEY]["disabled_sub_components"]) == {"base", "middle", "leaf"}
