"""
Tests for organisation bundle export/import (`GET /orgs/{id}/export`,
`POST /orgs/import`): settings, members (existing-account role grant vs.
invite-for-unmatched), report templates, nested projects, that Restricted
secrets (SMTP password, OIDC client secret) never appear in the exported
bytes, and bundle validation.
"""

import io
import zipfile

from tests.conftest import auth_headers, create_component_and_category, create_org_user, create_project, login


def test_export_never_includes_smtp_password_or_oidc_client_secret(client, admin_token, org_id):
    smtp_secret = "SuperSecretSmtpPassword123!"
    oidc_secret = "SuperSecretOidcClientSecret456!"
    adv_resp = client.put(
        f"/api/v1/orgs/{org_id}/advanced-settings",
        json={
            "smtp_host": "smtp.example.com", "smtp_port": 587, "smtp_username": "notifier@example.com",
            "smtp_password": smtp_secret, "smtp_use_tls": True, "sso_group_mappings": [],
        },
        headers=auth_headers(admin_token),
    )
    assert adv_resp.status_code == 200, adv_resp.text
    sso_resp = client.put(
        f"/api/v1/orgs/{org_id}/sso-config",
        json={
            "slug": f"org-{org_id}", "sso_enabled": True, "sso_only": False, "oidc_issuer_url": "https://idp.example.com",
            "oidc_client_id": "reqtrack-client", "oidc_client_secret": oidc_secret,
        },
        headers=auth_headers(admin_token),
    )
    assert sso_resp.status_code == 200, sso_resp.text

    export_resp = client.get(f"/api/v1/orgs/{org_id}/export", headers=auth_headers(admin_token))
    assert export_resp.status_code == 200
    assert export_resp.headers["content-type"] == "application/zip"
    raw_zip_bytes = export_resp.content
    assert smtp_secret.encode() not in raw_zip_bytes
    assert oidc_secret.encode() not in raw_zip_bytes

    zf = zipfile.ZipFile(io.BytesIO(raw_zip_bytes))
    org_json_text = zf.read("org.json").decode("utf-8")
    assert smtp_secret not in org_json_text
    assert oidc_secret not in org_json_text
    assert "smtp_password" not in org_json_text
    assert "oidc_client_secret" not in org_json_text
    # Non-secret config is still present for reference.
    assert "smtp.example.com" in org_json_text
    assert "reqtrack-client" in org_json_text


def test_export_contains_manifest_and_nested_projects(client, admin_token, org_id):
    project_one = create_project(client, admin_token, org_id, name="Org Export Project One")
    create_component_and_category(client, admin_token, project_one["id"])
    project_two = create_project(client, admin_token, org_id, name="Org Export Project Two")
    create_component_and_category(client, admin_token, project_two["id"])

    resp = client.get(f"/api/v1/orgs/{org_id}/export", headers=auth_headers(admin_token))
    assert resp.status_code == 200
    zf = zipfile.ZipFile(io.BytesIO(resp.content))
    names = zf.namelist()
    assert "manifest.json" in names
    assert "org.json" in names
    project_entries = [n for n in names if n.startswith("projects/") and n.endswith("/project.json")]
    assert len(project_entries) == 2

    import json
    manifest = json.loads(zf.read("manifest.json"))
    assert manifest["kind"] == "org-export"
    assert manifest["format_version"] == 1


def test_import_creates_new_org_grants_role_to_existing_user_and_invites_unmatched(client, admin_token, org_id):
    create_org_user(client, admin_token, org_id, "org-export-member@example.com", role="member")
    project = create_project(client, admin_token, org_id, name="Org Export Members Project")
    create_component_and_category(client, admin_token, project["id"])

    export_resp = client.get(f"/api/v1/orgs/{org_id}/export", headers=auth_headers(admin_token))
    assert export_resp.status_code == 200

    import_resp = client.post(
        "/api/v1/orgs/import",
        data={"name": "Imported Copy Of Org"},
        files={"file": ("bundle.zip", export_resp.content, "application/zip")},
        headers=auth_headers(admin_token),
    )
    assert import_resp.status_code == 201, import_resp.text
    body = import_resp.json()
    new_org = body["organization"]
    assert new_org["name"] == "Imported Copy Of Org"
    assert new_org["id"] != org_id
    assert new_org["is_active"] is True

    # The existing member@example.com account should have been granted a
    # real role in the new org (found by email match).
    org_users = client.get(f"/api/v1/orgs/{new_org['id']}/users", headers=auth_headers(admin_token)).json()
    emails_and_roles = {u["email"]: set(u["roles"]) for u in org_users}
    assert "org-export-member@example.com" in emails_and_roles
    assert "member" in emails_and_roles["org-export-member@example.com"]

    # The imported org's own project structure round-tripped.
    new_projects = client.get(f"/api/v1/projects?organization_id={new_org['id']}", headers=auth_headers(admin_token)).json()
    assert any(p["name"] == "Org Export Members Project" for p in new_projects)


def test_import_invites_a_member_with_no_existing_account(client, admin_token, org_id):
    """Every account in this suite is real and global (users are never
    deleted — see models.user.User), so there's no way to produce a
    genuinely unmatched member email by exporting real data; this
    hand-builds a bundle with one instead, mirroring
    test_project_export_import.py's equivalent unit-level test."""
    import json

    from sqlalchemy import select

    from app.database import SessionLocal
    from app.models.user import User
    from app.services.org_export import import_org_bundle

    export_resp = client.get(f"/api/v1/orgs/{org_id}/export", headers=auth_headers(admin_token))
    assert export_resp.status_code == 200
    zf_in = zipfile.ZipFile(io.BytesIO(export_resp.content))
    org_data = json.loads(zf_in.read("org.json"))
    org_data["members"].append({"email": "totally-unmatched-ghost@example.com", "display_name": "Ghost", "org_role": "org_admin"})
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf_out:
        for name in zf_in.namelist():
            zf_out.writestr(name, json.dumps(org_data) if name == "org.json" else zf_in.read(name))

    db = SessionLocal()
    try:
        importing_user = db.scalar(select(User).where(User.email == "admin@example.com"))
        _org, warnings = import_org_bundle(db, name="Ghost Member Org", zip_bytes=buffer.getvalue(), current_user=importing_user)
        assert any("totally-unmatched-ghost@example.com" in w for w in warnings)
        assert any("org_admin" in w for w in warnings)
    finally:
        db.close()


def test_export_denies_users_without_org_admin_role(client, admin_token, org_id):
    member_email = "org-export-denied@example.com"
    create_org_user(client, admin_token, org_id, member_email, role="member")
    member_token = login(client, member_email, "Password123!")
    resp = client.get(f"/api/v1/orgs/{org_id}/export", headers=auth_headers(member_token))
    assert resp.status_code == 403


def test_import_requires_server_admin(client, admin_token, org_id):
    export_resp = client.get(f"/api/v1/orgs/{org_id}/export", headers=auth_headers(admin_token))
    org_admin_email = "org-import-not-server-admin@example.com"
    create_org_user(client, admin_token, org_id, org_admin_email, role="org_admin")
    non_server_admin_token = login(client, org_admin_email, "Password123!")
    resp = client.post(
        "/api/v1/orgs/import",
        data={"name": "Should Not Be Created"},
        files={"file": ("bundle.zip", export_resp.content, "application/zip")},
        headers=auth_headers(non_server_admin_token),
    )
    assert resp.status_code == 403


def test_import_rejects_a_bundle_of_the_wrong_kind(client, admin_token):
    import json

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("manifest.json", json.dumps({"kind": "project-export", "format_version": 1}))
        zf.writestr("org.json", json.dumps({}))
    resp = client.post(
        "/api/v1/orgs/import",
        data={"name": "Bad Bundle"},
        files={"file": ("bundle.zip", buffer.getvalue(), "application/zip")},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 400


def test_import_rejects_a_non_zip_file(client, admin_token):
    resp = client.post(
        "/api/v1/orgs/import",
        data={"name": "Not A Zip"},
        files={"file": ("bundle.zip", b"not a zip file", "application/zip")},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 400


def test_import_rejects_a_raw_upload_over_the_size_limit(client, admin_token, org_id, monkeypatch):
    """See test_project_export_import.py's equivalent test: same two-layer
    zip-bomb defense in `services.bundle_common`, shared by both bundle kinds."""
    monkeypatch.setattr("app.services.bundle_common.MAX_IMPORT_UPLOAD_BYTES", 10)
    export_resp = client.get(f"/api/v1/orgs/{org_id}/export", headers=auth_headers(admin_token))
    assert len(export_resp.content) > 10
    resp = client.post(
        "/api/v1/orgs/import",
        data={"name": "Too Big"},
        files={"file": ("bundle.zip", export_resp.content, "application/zip")},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 413


def test_import_rejects_a_bundle_whose_declared_uncompressed_size_exceeds_the_cap(client, admin_token, org_id, monkeypatch):
    monkeypatch.setattr("app.services.bundle_common.MAX_BUNDLE_UNCOMPRESSED_BYTES", 10)
    export_resp = client.get(f"/api/v1/orgs/{org_id}/export", headers=auth_headers(admin_token))
    resp = client.post(
        "/api/v1/orgs/import",
        data={"name": "Too Big Uncompressed"},
        files={"file": ("bundle.zip", export_resp.content, "application/zip")},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 413
