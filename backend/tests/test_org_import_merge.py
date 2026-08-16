"""
Tests for merging an organisation export bundle into an *existing*
organisation (`POST /orgs/{id}/import/preview`, `POST
/orgs/{id}/import/merge`, `services.org_export.detect_merge_conflicts`/
`merge_org_bundle`) — as opposed to `POST /orgs/import`
(`test_org_export_import.py`), which always creates a brand-new
organisation. Covers: no-conflict merge (users/groups/projects/report
templates all added), a project-name collision resolved both ways
(skip/import-as-copy), a report-template-name collision resolved both ways
(keep-existing/use-import), that the target organisation's own profile
(branding/SMTP/SSO) is never touched, and the 400s for an incomplete or
invalid `resolutions` payload.
"""

import io
import zipfile

from tests.conftest import auth_headers, create_component_and_category, create_org_admin_in, create_org_user, create_project


def _export(client, token, org_id):
    resp = client.get(f"/api/v1/orgs/{org_id}/export", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return resp.content


def _preview(client, token, target_org_id, bundle_bytes):
    resp = client.post(
        f"/api/v1/orgs/{target_org_id}/import/preview",
        files={"file": ("bundle.zip", bundle_bytes, "application/zip")},
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["conflicts"]


def _merge(client, token, target_org_id, bundle_bytes, resolutions):
    import json

    resp = client.post(
        f"/api/v1/orgs/{target_org_id}/import/merge",
        files={"file": ("bundle.zip", bundle_bytes, "application/zip")},
        data={"resolutions": json.dumps(resolutions)},
        headers=auth_headers(token),
    )
    return resp


def test_merge_with_no_conflicts_adds_users_groups_projects_and_templates(client, admin_token, org_id):
    source_org, source_token = create_org_admin_in(client, admin_token, "Merge Source Org")
    create_org_user(client, admin_token, source_org["id"], "merge-source-member@example.com", role="member")
    project = create_project(client, source_token, source_org["id"], name="Merge Source Project")
    create_component_and_category(client, source_token, project["id"])
    group_resp = client.post(
        f"/api/v1/orgs/{source_org['id']}/groups", json={"name": "Merge Source Group"}, headers=auth_headers(source_token),
    )
    assert group_resp.status_code == 201, group_resp.text
    template_resp = client.post(
        f"/api/v1/orgs/{source_org['id']}/report-templates", json={"name": "Merge Source Template"},
        headers=auth_headers(source_token),
    )
    assert template_resp.status_code == 201, template_resp.text

    target_org, target_token = create_org_admin_in(client, admin_token, "Merge Target Org Clean")
    bundle_bytes = _export(client, source_token, source_org["id"])

    conflicts = _preview(client, target_token, target_org["id"], bundle_bytes)
    assert conflicts == []

    merge_resp = _merge(client, target_token, target_org["id"], bundle_bytes, resolutions={})
    assert merge_resp.status_code == 200, merge_resp.text
    body = merge_resp.json()
    assert body["projects_imported"] == 1
    assert body["projects_skipped"] == 0
    assert body["report_templates_imported"] == 1
    assert body["report_templates_overwritten"] == 0

    target_projects = client.get(f"/api/v1/projects?organization_id={target_org['id']}", headers=auth_headers(target_token)).json()
    assert any(p["name"] == "Merge Source Project" for p in target_projects)

    target_users = client.get(f"/api/v1/orgs/{target_org['id']}/users", headers=auth_headers(target_token)).json()
    emails = {u["email"] for u in target_users}
    assert "merge-source-member@example.com" in emails

    target_groups = client.get(f"/api/v1/orgs/{target_org['id']}/groups", headers=auth_headers(target_token)).json()
    assert any(g["name"] == "Merge Source Group" for g in target_groups)

    target_templates = client.get(f"/api/v1/orgs/{target_org['id']}/report-templates", headers=auth_headers(target_token)).json()
    assert any(t["name"] == "Merge Source Template" for t in target_templates)


def test_merge_project_name_conflict_can_be_skipped_or_imported_as_a_copy(client, admin_token):
    source_org, source_token = create_org_admin_in(client, admin_token, "Merge Project Conflict Source")
    create_project(client, source_token, source_org["id"], name="Shared Project Name")
    bundle_bytes = _export(client, source_token, source_org["id"])

    target_org, target_token = create_org_admin_in(client, admin_token, "Merge Project Conflict Target")
    existing = create_project(client, target_token, target_org["id"], name="Shared Project Name")

    conflicts = _preview(client, target_token, target_org["id"], bundle_bytes)
    assert len(conflicts) == 1
    conflict = conflicts[0]
    assert conflict["kind"] == "project"
    assert conflict["name"] == "Shared Project Name"
    assert conflict["existing_id"] == existing["id"]

    # Skip: the target's existing project is untouched, nothing new is added.
    skip_resp = _merge(client, target_token, target_org["id"], bundle_bytes, resolutions={conflict["id"]: "skip"})
    assert skip_resp.status_code == 200, skip_resp.text
    assert skip_resp.json()["projects_imported"] == 0
    assert skip_resp.json()["projects_skipped"] == 1
    projects_after_skip = client.get(f"/api/v1/projects?organization_id={target_org['id']}", headers=auth_headers(target_token)).json()
    assert len([p for p in projects_after_skip if p["name"] == "Shared Project Name"]) == 1

    # Import as copy: the bundle's project is added alongside the existing one, renamed.
    copy_resp = _merge(client, target_token, target_org["id"], bundle_bytes, resolutions={conflict["id"]: "import_as_copy"})
    assert copy_resp.status_code == 200, copy_resp.text
    assert copy_resp.json()["projects_imported"] == 1
    projects_after_copy = client.get(f"/api/v1/projects?organization_id={target_org['id']}", headers=auth_headers(target_token)).json()
    assert any(p["name"] == "Shared Project Name (imported)" for p in projects_after_copy)
    assert len([p for p in projects_after_copy if p["name"] == "Shared Project Name"]) == 1


def test_merge_report_template_conflict_can_be_kept_or_overwritten(client, admin_token):
    source_org, source_token = create_org_admin_in(client, admin_token, "Merge Template Conflict Source")
    client.post(
        f"/api/v1/orgs/{source_org['id']}/report-templates",
        json={"name": "Shared Template", "footer_text": "From the source org"},
        headers=auth_headers(source_token),
    )
    bundle_bytes = _export(client, source_token, source_org["id"])

    target_org, target_token = create_org_admin_in(client, admin_token, "Merge Template Conflict Target")
    existing = client.post(
        f"/api/v1/orgs/{target_org['id']}/report-templates",
        json={"name": "Shared Template", "footer_text": "From the target org"},
        headers=auth_headers(target_token),
    ).json()

    conflicts = _preview(client, target_token, target_org["id"], bundle_bytes)
    assert len(conflicts) == 1
    conflict = conflicts[0]
    assert conflict["kind"] == "report_template"
    assert conflict["existing_id"] == existing["id"]

    keep_resp = _merge(client, target_token, target_org["id"], bundle_bytes, resolutions={conflict["id"]: "keep_existing"})
    assert keep_resp.status_code == 200, keep_resp.text
    assert keep_resp.json()["report_templates_overwritten"] == 0
    templates = client.get(f"/api/v1/orgs/{target_org['id']}/report-templates", headers=auth_headers(target_token)).json()
    assert next(t for t in templates if t["name"] == "Shared Template")["footer_text"] == "From the target org"

    use_import_resp = _merge(client, target_token, target_org["id"], bundle_bytes, resolutions={conflict["id"]: "use_import"})
    assert use_import_resp.status_code == 200, use_import_resp.text
    assert use_import_resp.json()["report_templates_overwritten"] == 1
    templates = client.get(f"/api/v1/orgs/{target_org['id']}/report-templates", headers=auth_headers(target_token)).json()
    assert next(t for t in templates if t["name"] == "Shared Template")["footer_text"] == "From the source org"


def test_merge_never_touches_the_target_orgs_own_profile(client, admin_token):
    source_org, source_token = create_org_admin_in(client, admin_token, "Merge Profile Source")
    client.put(
        f"/api/v1/orgs/{source_org['id']}/branding",
        json={"accent_color_hex": "#112233", "header_title": "Source Header"},
        headers=auth_headers(source_token),
    )
    bundle_bytes = _export(client, source_token, source_org["id"])

    target_org, target_token = create_org_admin_in(client, admin_token, "Merge Profile Target")
    branding_resp = client.put(
        f"/api/v1/orgs/{target_org['id']}/branding",
        json={"accent_color_hex": "#445566", "header_title": "Target Header"},
        headers=auth_headers(target_token),
    )
    assert branding_resp.status_code == 200, branding_resp.text

    merge_resp = _merge(client, target_token, target_org["id"], bundle_bytes, resolutions={})
    assert merge_resp.status_code == 200, merge_resp.text

    target_after = client.get(f"/api/v1/orgs/{target_org['id']}", headers=auth_headers(target_token)).json()
    assert target_after["accent_color_hex"] == "#445566"
    assert target_after["header_title"] == "Target Header"


def test_merge_requires_a_resolution_for_every_conflict(client, admin_token):
    source_org, source_token = create_org_admin_in(client, admin_token, "Merge Missing Resolution Source")
    create_project(client, source_token, source_org["id"], name="Unresolved Project")
    bundle_bytes = _export(client, source_token, source_org["id"])

    target_org, target_token = create_org_admin_in(client, admin_token, "Merge Missing Resolution Target")
    create_project(client, target_token, target_org["id"], name="Unresolved Project")

    resp = _merge(client, target_token, target_org["id"], bundle_bytes, resolutions={})
    assert resp.status_code == 400


def test_merge_rejects_an_invalid_resolution_value(client, admin_token):
    source_org, source_token = create_org_admin_in(client, admin_token, "Merge Invalid Resolution Source")
    create_project(client, source_token, source_org["id"], name="Invalid Resolution Project")
    bundle_bytes = _export(client, source_token, source_org["id"])

    target_org, target_token = create_org_admin_in(client, admin_token, "Merge Invalid Resolution Target")
    create_project(client, target_token, target_org["id"], name="Invalid Resolution Project")

    conflicts = _preview(client, target_token, target_org["id"], bundle_bytes)
    resp = _merge(client, target_token, target_org["id"], bundle_bytes, resolutions={conflicts[0]["id"]: "not_a_real_choice"})
    assert resp.status_code == 400


def test_merge_requires_org_admin_of_the_target_organisation(client, admin_token):
    source_org, source_token = create_org_admin_in(client, admin_token, "Merge Auth Source")
    create_project(client, source_token, source_org["id"], name="Auth Test Project")
    bundle_bytes = _export(client, source_token, source_org["id"])

    target_org, _target_token = create_org_admin_in(client, admin_token, "Merge Auth Target")

    # source_token is a genuine org_admin, just not of the target org.
    resp = client.post(
        f"/api/v1/orgs/{target_org['id']}/import/preview",
        files={"file": ("bundle.zip", bundle_bytes, "application/zip")},
        headers=auth_headers(source_token),
    )
    assert resp.status_code == 403


def test_merge_rejects_a_bundle_of_the_wrong_kind(client, admin_token, org_id):
    import json

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("manifest.json", json.dumps({"kind": "project-export", "format_version": 1}))
        zf.writestr("org.json", json.dumps({}))
    resp = client.post(
        f"/api/v1/orgs/{org_id}/import/preview",
        files={"file": ("bundle.zip", buffer.getvalue(), "application/zip")},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 400
