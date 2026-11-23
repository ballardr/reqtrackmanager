"""Tests that the project-level Compliance nav entry is advertised only once its organisation has an assignable
standard. `routers.projects.list_project_enabled_modules` (`GET /api/v1/projects/{id}/enabled-modules`) attaches the
compliance `frontend_manifest` only when the organisation has a `ComplianceStandardVersion` with `status == PUBLISHED`:
a DRAFT-only standard has nothing to assign, so the link would open an empty "assign a standard" page. As for a rejected
Tier B `frame_url` (`test_module_frontend_integration.py`), the manifest is omitted and the nav entry absent.

The file is independent of `test_compliance_standards_api.py`'s `_create_standard` and `_create_version` helpers, so it
is unaffected by changes to the standard-creation payload.
"""

from __future__ import annotations

from tests.conftest import auth_headers, create_project


def _base(org_id: str) -> str:
    return f"/api/v1/orgs/{org_id}/modules/compliance"


def test_compliance_nav_entry_absent_until_a_standard_version_is_published(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id, "Nav Gating Project")

    def compliance_manifest():
        # Every enabled module gets a `ModuleNavEntryOut` row whether or not it has anything to contribute (the entry
        # stays, `frontend_manifest` goes `None`, as for a rejected Tier B manifest); `Layout.tsx` renders nothing for a
        # `None` manifest, which is the field this test pins.
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
    # with the project id already interpolated into its paths (existing
    # behaviour, unaffected by this gate).
    manifest = compliance_manifest()
    assert manifest is not None
    assert manifest["nav_path"] == f"/projects/{project['id']}/modules/compliance"
