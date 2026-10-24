"""Every module travels in the project and organisation bundles.

A registered module either contributes `ModuleProjectBundleHooks` / `ModuleOrgBundleHooks` or states why it has
nothing at that level (`no_project_bundle` / `no_org_bundle`), so a new module cannot ship data that a project or
organisation export silently drops. The sections modules contribute are merged into one JSON object, so their
keys must not collide with each other or with a core section (a collision would overwrite data without an error).
"""

from __future__ import annotations

import io
import json
import uuid
import zipfile

from app.database import SessionLocal
from app.models.organization import Organization
from app.models.project import Project
from app.models.user import User
from app.modules.registry import (
    get_all_module_org_bundle_hooks,
    get_all_module_project_bundle_hooks,
    get_module_registry,
)
from app.services import org_export, project_export
from tests.conftest import create_org_admin_in, create_project


def test_every_module_has_bundle_hooks_or_a_reason():
    """A module that stores per-project or per-organisation data must export it; one that does not says why."""
    missing = []
    for key, definition in get_module_registry().items():
        if definition.project_bundle_hooks is None and not definition.no_project_bundle:
            missing.append(f"{key}: no project_bundle_hooks and no no_project_bundle reason")
        if definition.org_bundle_hooks is None and not definition.no_org_bundle:
            missing.append(f"{key}: no org_bundle_hooks and no no_org_bundle reason")
        if definition.project_bundle_hooks is not None and definition.no_project_bundle:
            missing.append(f"{key}: has project_bundle_hooks and also a no_project_bundle reason")
        if definition.org_bundle_hooks is not None and definition.no_org_bundle:
            missing.append(f"{key}: has org_bundle_hooks and also a no_org_bundle reason")
    assert not missing, "\n".join(missing)


def test_module_bundle_sections_do_not_collide_with_each_other_or_core(client, admin_token, monkeypatch):
    org_row, token = create_org_admin_in(client, admin_token, "Bundle Keys Co")
    project_row = create_project(client, token, org_row["id"], "Bundle Keys Project")
    db = SessionLocal()
    try:
        org, project = db.get(Organization, uuid.UUID(org_row["id"])), db.get(Project, uuid.UUID(project_row["id"]))
        exporter = db.query(User).first()

        project_keys = {key: set(hooks.export(db, project)[0]) for key, hooks in get_all_module_project_bundle_hooks()}
        org_keys = {key: set(hooks.export(db, org)) for key, hooks in get_all_module_org_bundle_hooks()}

        monkeypatch.setattr(project_export, "get_all_module_project_bundle_hooks", lambda: [])
        monkeypatch.setattr(org_export, "get_all_module_org_bundle_hooks", lambda: [])
        core_project = set(project_export.collect_project_data(db, project)[0])
        bundle = org_export.build_org_bundle(db, org, exporter)
        core_org = set(json.loads(zipfile.ZipFile(io.BytesIO(bundle)).read("org.json")))
    finally:
        db.close()

    for level, by_module, core in (("project", project_keys, core_project), ("organisation", org_keys, core_org)):
        seen: dict[str, str] = {}
        for module_key, keys in by_module.items():
            for name in keys:
                assert name not in core, f"{level} bundle: {module_key!r} section {name!r} overwrites a core section"
                assert name not in seen, f"{level} bundle: {module_key!r} and {seen[name]!r} both write section {name!r}"
                seen[name] = module_key
