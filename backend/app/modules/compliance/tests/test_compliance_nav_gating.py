"""Tests for Phase 17e: the project-level Compliance nav entry/route is only
advertised once its organisation has a real, assignable standard.

`routers.projects.list_project_enabled_modules` (`GET /api/v1/projects/
{id}/enabled-modules`) special-cases `definition.key == "compliance"`: its
`frontend_manifest` is only attached when the project's organisation has at
least one `ComplianceStandardVersion` with `status == PUBLISHED` — a
DRAFT-only standard has nothing a project could actually be assigned, so
the nav link/route would otherwise send a user to an empty "assign a
standard" page with nothing to pick from. This mirrors the existing
mechanism `test_module_frontend_integration.py` already covers for a
rejected Tier B `frame_url` (manifest silently omitted -> nav entry
silently absent), just gated on org data instead of manifest validation.

A standalone file rather than an addition to `test_compliance_standards_
api.py`: kept deliberately independent of that file's shared `_create_
standard`/`_create_version` helpers so it has nothing to reconcile against
Phase 17b's concurrent change to the standard-creation payload shape.
"""

from __future__ import annotations

from tests.conftest import auth_headers, create_project


def _base(org_id: str) -> str:
    return f"/api/v1/orgs/{org_id}/modules/compliance"


def test_compliance_nav_entry_absent_until_a_standard_version_is_published(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id, "Nav Gating Project")

    def compliance_manifest():
        # Every enabled module gets a `ModuleNavEntryOut` row regardless of
        # whether it currently has anything to contribute (mirrors the
        # existing Tier-B-rejected-manifest precedent, `test_module_
        # frontend_integration.py::test_org_modules_endpoint_omits_manifest_
        # for_a_rejected_remote_module` — the entry stays, `frontend_
        # manifest` goes `None`); `Layout.tsx`'s `enabledModules.map(...)`
        # already renders nothing for a `None` manifest, so that's the field
        # this test actually needs to pin, not the entry's presence.
        resp = client.get(f"/api/v1/projects/{project['id']}/enabled-modules", headers=auth_headers(admin_token))
        assert resp.status_code == 200, resp.text
        entry = next((m for m in resp.json() if m["module_key"] == "compliance"), None)
        assert entry is not None, "compliance module itself should always be listed once enabled"
        return entry["frontend_manifest"]

    # Compliance is enabled for this org (default_enabled=True) but has zero
    # standards at all yet -> no manifest.
    assert compliance_manifest() is None

    resp = client.post(
        f"{_base(org_id)}/standards",
        json={
            "reference": "NAV-GATE-1", "name": "Nav Gating Standard",
            "initial_version_label": "1.0",
        },
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 201, resp.text
    standard = resp.json()

    # A standard exists now, but its only version is still DRAFT -> still
    # nothing assignable, still no manifest.
    assert compliance_manifest() is None

    versions_resp = client.get(f"{_base(org_id)}/standards/{standard['id']}/versions", headers=auth_headers(admin_token))
    assert versions_resp.status_code == 200, versions_resp.text
    version = versions_resp.json()[0]

    publish_resp = client.post(
        f"{_base(org_id)}/standards/{standard['id']}/versions/{version['id']}/publish",
        headers=auth_headers(admin_token),
    )
    assert publish_resp.status_code == 200, publish_resp.text

    # Publishing the version makes it assignable -> the manifest appears,
    # with the project id already interpolated into its paths (Phase 13's
    # own existing behaviour, unaffected by this gate).
    manifest = compliance_manifest()
    assert manifest is not None
    assert manifest["nav_path"] == f"/projects/{project['id']}/modules/compliance"
