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

from sqlalchemy import select

from app.database import SessionLocal
from app.models.audit import AuditEvent
from tests.conftest import auth_headers, create_component_and_category, create_org_admin_in, create_org_user, create_project, login


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


def test_merge_audit_event_records_the_source_bundles_provenance(client, admin_token):
    """A merge writes into the target org's own real data, crossing an
    existing tenant boundary `import_org_bundle` never has to (see
    `merge_org_bundle`'s docstring) — "who did this" (`actor_id`) alone
    isn't enough for an incident review to trace *where the data came
    from*, so the audit event's `detail` must also carry the bundle's own
    self-reported provenance (source org name, exporter, export time)."""
    source_org, source_token = create_org_admin_in(client, admin_token, "Merge Audit Provenance Source")
    bundle_bytes = _export(client, source_token, source_org["id"])

    target_org, target_token = create_org_admin_in(client, admin_token, "Merge Audit Provenance Target")
    merge_resp = _merge(client, target_token, target_org["id"], bundle_bytes, resolutions={})
    assert merge_resp.status_code == 200, merge_resp.text

    db = SessionLocal()
    try:
        event = db.scalar(
            select(AuditEvent)
            .where(AuditEvent.action == "merged_from_bundle", AuditEvent.entity_id == target_org["id"])
        )
    finally:
        db.close()
    assert event is not None
    assert event.detail["source_org_name"] == "Merge Audit Provenance Source"
    assert event.detail["source_exported_by_email"]
    assert event.detail["source_exported_at"]


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


def test_merge_does_not_grant_a_role_or_group_membership_to_a_banned_member(client, admin_token, org_id):
    """Hardening-review finding: `_import_members`/`_import_org_groups` are
    a third and fourth way to hand out org access (alongside
    `assign_org_role` and `assign_project_role_by_email`), and neither
    originally checked `User.is_banned` — a target org_admin could
    otherwise use a merge to quietly let a banned account back in (an org
    role directly, or project access via an org group nested into a
    `ProjectGroup`), bypassing the ban the same way `assign_org_role`
    itself refuses to.

    Exported *before* the account is orphaned/banned (both `ban` and
    `add_org_group_member` require the target to currently have — or, for
    `add_org_group_member`, to still have — real org membership, so the
    only way to get a real bundle containing this member/group state at
    all is to capture it first, then have the account leave and get
    banned afterwards) — which is also the realistic shape of this gap: an
    org exported for backup/migration today, and one of its members banned
    tomorrow, must not let that ban be silently undone by merging in the
    now-stale bundle next week.
    """
    banned_email = "merge-banned-member@example.com"
    source_org, source_token = create_org_admin_in(client, admin_token, "Merge Banned Member Source")
    banned_id = create_org_user(client, source_token, source_org["id"], banned_email, role="org_admin")
    group_resp = client.post(
        f"/api/v1/orgs/{source_org['id']}/groups", json={"name": "Banned Member Group"}, headers=auth_headers(source_token),
    )
    assert group_resp.status_code == 201, group_resp.text
    add_member_resp = client.post(
        f"/api/v1/orgs/{source_org['id']}/groups/{group_resp.json()['id']}/members",
        json={"user_id": banned_id},
        headers=auth_headers(source_token),
    )
    assert add_member_resp.status_code == 204, add_member_resp.text
    bundle_bytes = _export(client, source_token, source_org["id"])

    banned_token = login(client, banned_email, "Password123!")
    leave_resp = client.delete(f"/api/v1/orgs/{source_org['id']}/membership", headers=auth_headers(banned_token))
    assert leave_resp.status_code == 204, leave_resp.text
    ban_resp = client.post(f"/api/v1/system/users/{banned_id}/ban", headers=auth_headers(admin_token))
    assert ban_resp.status_code == 204, ban_resp.text

    target_org, target_token = create_org_admin_in(client, admin_token, "Merge Banned Member Target")
    merge_resp = _merge(client, target_token, target_org["id"], bundle_bytes, resolutions={})
    assert merge_resp.status_code == 200, merge_resp.text
    warnings = merge_resp.json()["warnings"]
    assert any("banned" in w.lower() and banned_email in w for w in warnings)

    target_users = client.get(f"/api/v1/orgs/{target_org['id']}/users", headers=auth_headers(target_token)).json()
    assert banned_email not in {u["email"] for u in target_users}

    target_groups = client.get(f"/api/v1/orgs/{target_org['id']}/groups", headers=auth_headers(target_token)).json()
    group = next(g for g in target_groups if g["name"] == "Banned Member Group")
    assert banned_id not in group["member_user_ids"]


def test_merge_skips_an_invalid_granted_org_role_with_a_warning_instead_of_500ing(client, admin_token):
    """Hardening-review finding: `_import_org_groups` parsed a bundle
    group's `granted_org_role` with a bare `OrgRole(...)` call and no
    error handling, unlike every other untrusted-bundle-content case in
    the same function (a name collision on `idp_synced_group_name`, a
    cycle-forming nested edge, a banned member — all skipped with a
    warning rather than raised). A hand-crafted or corrupted bundle
    carrying a `granted_org_role` that isn't a real `OrgRole` value used
    to 500 the whole merge instead of being reported like any other
    malformed field; this pins the fix."""
    import json

    target_org, target_token = create_org_admin_in(client, admin_token, "Invalid Granted Role Target")

    manifest = {
        "kind": "org-export", "format_version": 1, "exported_at": "2026-08-25T00:00:00Z",
        "exported_by_email": "x@example.com", "org_name": "Bad Bundle",
    }
    org_json = {
        "name": "Bad Bundle", "accent_color_hex": None, "header_title": None,
        "require_2fa": False, "allow_self_signup": False, "auto_accept_email_domain": None,
        "external_user_policy": "disabled", "smtp_host": None, "smtp_port": None, "smtp_username": None,
        "smtp_use_tls": True, "source_sso_enabled": False, "source_sso_only": False,
        "oidc_issuer_url": None, "oidc_client_id": None, "oidc_required_group": None, "pat_max_lifetime_days": None,
        "default_report_intro": None, "default_report_chapters": None, "default_report_appendices": None,
        "logo_file_ref": None, "logo_content_type": None, "login_background_file_ref": None,
        "login_background_content_type": None, "default_template_project_ref": None,
        "report_templates": [], "members": [],
        "org_groups": [
            {
                "name": "Malformed Role Group", "member_emails": [], "nested_group_names": [],
                "idp_synced_group_name": "malformed-role-group", "granted_org_role": "not_a_real_role",
            },
        ],
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("manifest.json", json.dumps(manifest))
        zf.writestr("org.json", json.dumps(org_json))
    bundle_bytes = buffer.getvalue()

    merge_resp = _merge(client, target_token, target_org["id"], bundle_bytes, resolutions={})
    assert merge_resp.status_code == 200, merge_resp.text
    warnings = merge_resp.json()["warnings"]
    assert any("Malformed Role Group" in w and "granted role" in w for w in warnings)

    target_groups = client.get(f"/api/v1/orgs/{target_org['id']}/groups", headers=auth_headers(target_token)).json()
    group = next(g for g in target_groups if g["name"] == "Malformed Role Group")
    assert group["granted_org_role"] is None
    assert group["idp_synced_group_name"] == "malformed-role-group"


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
