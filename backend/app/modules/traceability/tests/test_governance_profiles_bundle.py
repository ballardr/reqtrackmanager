"""Tests for governance profiles in the organisation and project bundles (`modules.traceability.bundle`): the
organisation export and fresh import (profiles, targets by project reference, exemptions, policy rows through a
contributor), a merge into an organisation that already has a profile of the same name, and a project's choices on
project export, import and template copy. An import never relaxes an Enforced profile."""

from __future__ import annotations

import io
import json
import uuid as uuid_lib
import zipfile

from sqlalchemy import select

from app.database import SessionLocal
from app.models.project import Project
from app.models.user import User
from app.modules import registry as module_registry
from app.modules.registry import build_registry, get_module
from app.modules.traceability import bundle
from app.modules.traceability.models import (
    GovernanceProfile,
    GovernanceProfileChoice,
    GovernanceProfileExemption,
    GovernanceProfileTarget,
)
from app.modules.traceability.tests.test_governance_profiles import (
    FAKE_KEY,
    _choose,
    _create,
    _exempt,
    _fake_contributor,
    _fake_definition,
    _setup,
)
from app.services.bundle_common import BundleImportWarnings, UserResolver
from tests.conftest import auth_headers, create_project


def _export_org(client, token, org_id) -> bytes:
    resp = client.get(f"/api/v1/orgs/{org_id}/export", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return resp.content


def _profiles(org_id: str) -> dict[str, dict]:
    """The organisation's profiles by name with their targets, exemptions and choices by project name."""
    db = SessionLocal()
    try:
        names = {p.id: p.name for p in db.scalars(select(Project).where(Project.organization_id == uuid_lib.UUID(org_id)))}
        out: dict[str, dict] = {}
        for profile in db.scalars(select(GovernanceProfile).where(GovernanceProfile.organization_id == uuid_lib.UUID(org_id))):
            out[profile.name] = {
                "mode": profile.mode, "target_kind": profile.target_kind, "description": profile.description,
                "targets": sorted(
                    (names[t.project_id], t.include_children)
                    for t in db.scalars(select(GovernanceProfileTarget).where(GovernanceProfileTarget.profile_id == profile.id))
                ),
                "exemptions": sorted(
                    (names[e.project_id], e.include_children, e.reason)
                    for e in db.scalars(select(GovernanceProfileExemption).where(GovernanceProfileExemption.profile_id == profile.id))
                ),
                "choices": sorted(
                    (names[c.project_id], c.opted_in)
                    for c in db.scalars(select(GovernanceProfileChoice).where(GovernanceProfileChoice.profile_id == profile.id))
                ),
                "id": profile.id,
            }
        return out
    finally:
        db.close()


def _build_source(client, admin_token, name):
    org, token = _setup(client, admin_token, name)
    parent = create_project(client, token, org["id"], "Parent", can_be_parent=True)
    child = create_project(client, token, org["id"], "Child", parent_project_id=parent["id"])
    _create(client, token, org["id"], "Regulated", description="Regulated work")
    default = _create(client, token, org["id"], "Shared defaults", mode="default")
    _create(
        client, token, org["id"], "Selected", mode="opt_in", target_kind="selected_projects",
        targets=[{"project_id": child["id"], "include_children": True}],
    )
    regulated_id = next(p["id"] for p in _list(client, token, org["id"]) if p["name"] == "Regulated")
    _exempt(client, token, org["id"], regulated_id, parent["id"], include_children=True, reason="Pilot")
    _choose(client, token, child["id"], default["id"], False)
    return org, token, parent, child


def _list(client, token, org_id):
    return client.get(f"/api/v1/orgs/{org_id}/modules/traceability/profiles", headers=auth_headers(token)).json()


def _expected():
    return {
        "Regulated": {
            "mode": "enforced", "target_kind": "all_projects", "description": "Regulated work", "targets": [],
            "exemptions": [("Parent", True, "Pilot")], "choices": [],
        },
        "Shared defaults": {
            "mode": "default", "target_kind": "all_projects", "description": "", "targets": [], "exemptions": [],
            "choices": [("Child", False)],
        },
        "Selected": {
            "mode": "opt_in", "target_kind": "selected_projects", "description": "", "targets": [("Child", True)],
            "exemptions": [], "choices": [],
        },
    }


def _shape(by_name: dict[str, dict]) -> dict[str, dict]:
    return {name: {k: v for k, v in entry.items() if k != "id"} for name, entry in by_name.items()}


def test_organisation_export_import_round_trips_profiles(client, admin_token):
    org, token, _parent, _child = _build_source(client, admin_token, "Profile Bundle Source Org")
    assert _shape(_profiles(org["id"])) == _expected()
    exported = json.loads(zipfile.ZipFile(io.BytesIO(_export_org(client, token, org["id"]))).read("org.json"))
    assert {e["name"] for e in exported[bundle.PROFILES_KEY]} == set(_expected())
    assert all("project_ref" in e for e in exported[bundle.TARGETS_KEY] + exported[bundle.EXEMPTIONS_KEY])

    resp = client.post(
        "/api/v1/orgs/import", data={"name": "Profile Bundle Imported Org"},
        files={"file": ("bundle.zip", _export_org(client, token, org["id"]), "application/zip")},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code in (200, 201), resp.text
    imported_id = resp.json().get("id") or resp.json()["organization"]["id"]
    assert _shape(_profiles(imported_id)) == _expected()


def test_policy_rows_travel_with_their_profile(client, admin_token):
    rows: dict[uuid_lib.UUID, list[dict]] = {}
    module_registry.INSTALLED_MODULES.append(_fake_definition(profile_contributors=(_fake_contributor(rows),)))
    build_registry(force=True)
    try:
        org, token = _setup(client, admin_token, "Profile Contributor Bundle Org")
        profile = _create(client, token, org["id"], "Carries rows")
        rows[uuid_lib.UUID(profile["id"])] = [{"role": "reviewer"}, {"role": "approver"}]
        resp = client.post(
            "/api/v1/orgs/import", data={"name": "Profile Contributor Bundle Imported"},
            files={"file": ("bundle.zip", _export_org(client, token, org["id"]), "application/zip")},
            headers=auth_headers(admin_token),
        )
        assert resp.status_code in (200, 201), resp.text
        imported_id = resp.json().get("id") or resp.json()["organization"]["id"]
        new_id = _profiles(imported_id)["Carries rows"]["id"]
        assert rows[new_id] == [{"role": "reviewer"}, {"role": "approver"}]
    finally:
        module_registry.INSTALLED_MODULES[:] = [m for m in module_registry.INSTALLED_MODULES if m.key != FAKE_KEY]
        build_registry(force=True)


def test_a_merge_keeps_the_organisations_own_profile_and_adds_the_rest(client, admin_token):
    source, source_token, _parent, _child = _build_source(client, admin_token, "Profile Merge Source Org")
    target, target_token = _setup(client, admin_token, "Profile Merge Target Org")
    opened = client.put(
        f"/api/v1/orgs/{target['id']}/advanced-settings", json={"external_user_policy": "anyone"}, headers=auth_headers(target_token),
    )
    assert opened.status_code == 200, opened.text
    create_project(client, target_token, target["id"], "Target project")
    _create(client, target_token, target["id"], "Regulated", mode="opt_in", description="The target's own")

    resp = client.post(
        f"/api/v1/orgs/{target['id']}/import/merge",
        files={"file": ("bundle.zip", _export_org(client, source_token, source["id"]), "application/zip")},
        data={"resolutions": json.dumps({})}, headers=auth_headers(target_token),
    )
    assert resp.status_code == 200, resp.text
    merged = _profiles(target["id"])
    assert merged["Regulated"]["mode"] == "opt_in" and merged["Regulated"]["description"] == "The target's own"
    assert merged["Regulated"]["exemptions"] == []  # nothing of the imported profile touched the kept one
    assert merged["Shared defaults"]["mode"] == "default" and merged["Selected"]["mode"] == "opt_in"
    assert merged["Selected"]["targets"] == [("Child", True)]
    assert merged["Shared defaults"]["choices"] == [("Child", False)]
    assert any("Regulated" in w and "kept unchanged" in w for w in resp.json().get("warnings", []))


def test_project_export_import_round_trips_choices_by_profile_name(client, admin_token):
    org, token = _setup(client, admin_token, "Profile Project Bundle Org")
    project = create_project(client, token, org["id"], "Source")
    default = _create(client, token, org["id"], "Default set", mode="default")
    optional = _create(client, token, org["id"], "Opt-in set", mode="opt_in")
    _choose(client, token, project["id"], default["id"], False)
    _choose(client, token, project["id"], optional["id"], True)
    exported = client.get(f"/api/v1/projects/{project['id']}/export", headers=auth_headers(token))
    assert exported.status_code == 200, exported.text

    imported = client.post(
        "/api/v1/projects/import", data={"organization_id": org["id"], "name": "Copy"},
        files={"file": ("bundle.zip", exported.content, "application/zip")}, headers=auth_headers(token),
    )
    assert imported.status_code == 201, imported.text
    by_name = _profiles(org["id"])
    assert sorted(by_name["Default set"]["choices"]) == [("Copy", False), ("Source", False)]
    assert sorted(by_name["Opt-in set"]["choices"]) == [("Copy", True), ("Source", True)]


def test_a_project_import_never_relaxes_an_enforced_profile(client, admin_token):
    org, token = _setup(client, admin_token, "Profile Import Enforced Org")
    project = create_project(client, token, org["id"], "Target")
    _create(client, token, org["id"], "Enforced set")
    _create(client, token, org["id"], "Opt-in set", mode="opt_in")
    me = uuid_lib.UUID(client.get("/api/v1/auth/me", headers=auth_headers(token)).json()["id"])
    db = SessionLocal()
    try:
        warnings = BundleImportWarnings()
        row = db.get(Project, uuid_lib.UUID(project["id"]))
        user = db.get(User, me)
        assert row is not None and user is not None
        resolver = UserResolver(db, user, warnings, organization_id=uuid_lib.UUID(org["id"]))
        bundle.import_project_data(
            db, row, {bundle.CHOICES_KEY: [
                {"profile": "Enforced set", "opted_in": False},   # an Enforced profile takes no choice
                {"profile": "Missing set", "opted_in": True},     # not in this organisation
                {"profile": "Opt-in set", "opted_in": False},     # an Opt-in profile takes only an opt-in
            ]}, {}, user, resolver, warnings,
        )
        db.commit()
        assert len(warnings.messages) == 3
        assert any("Missing set" in m for m in warnings.messages)
        assert db.scalar(select(GovernanceProfileChoice.id)) is None
    finally:
        db.close()


def test_choices_are_template_configuration():
    definition = get_module("traceability")
    assert definition is not None
    hooks = definition.project_bundle_hooks
    assert hooks is not None and hooks.template_configuration_keys == {bundle.CHOICES_KEY}
    assert not hooks.template_record_keys and not hooks.template_excluded
