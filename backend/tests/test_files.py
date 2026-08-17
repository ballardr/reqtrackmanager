"""Tests for file storage (I-M-10): requirement attachments (C-M-02), org
shared resources (C-M-03), linking a shared resource to a requirement
(C-M-04), and avatar/logo upload (C-U-18, U-C-02)."""

from sqlalchemy import text

from app.database import engine as app_engine
from tests.conftest import auth_headers, create_component_and_category, create_project


def _create_requirement(client, admin_token, project_id, component_id, category_id):
    return client.post(
        f"/api/v1/projects/{project_id}/requirements",
        json={"name": "Req", "component_id": component_id, "category_id": category_id},
        headers=auth_headers(admin_token),
    ).json()


def test_upload_and_download_requirement_attachment(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    requirement = _create_requirement(client, admin_token, project["id"], component_id, category_id)

    resp = client.post(
        f"/api/v1/projects/{project['id']}/requirements/{requirement['id']}/files",
        files={"file": ("spec.txt", b"hello world", "text/plain")},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 201
    file_id = resp.json()["id"]
    assert resp.json()["filename"] == "spec.txt"

    listed = client.get(
        f"/api/v1/projects/{project['id']}/requirements/{requirement['id']}/files",
        headers=auth_headers(admin_token),
    ).json()
    assert len(listed) == 1

    download = client.get(f"/api/v1/files/{file_id}", headers=auth_headers(admin_token))
    assert download.status_code == 200
    assert download.content == b"hello world"

    resp = client.delete(
        f"/api/v1/projects/{project['id']}/requirements/{requirement['id']}/files/{file_id}",
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 204
    download = client.get(f"/api/v1/files/{file_id}", headers=auth_headers(admin_token))
    assert download.status_code == 404


def test_uploaded_filename_cannot_escape_its_organisations_storage_key_prefix(client, admin_token, org_id):
    """Regression test for a hardening-review finding: a crafted filename
    like `../../other-org/evil.txt` used to reintroduce real path
    traversal into the generated storage key (the uuid prefix only
    neutralises the *first* `../` segment by merging with it into one
    literal component, leaving any additional ones as live traversal
    operators) — letting an upload resolve into a different organisation's
    key prefix on the local storage backend while still passing its own
    confinement check. The storage key itself isn't exposed via the API,
    so this asserts directly against the DB row that it's confined to
    `{organization_id}/` with no path separators or `..` from the filename
    surviving into it, and that the file still round-trips correctly."""
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    requirement = _create_requirement(client, admin_token, project["id"], component_id, category_id)

    malicious_name = "../../../some-other-org-id/evil.txt"
    resp = client.post(
        f"/api/v1/projects/{project['id']}/requirements/{requirement['id']}/files",
        files={"file": (malicious_name, b"payload", "text/plain")},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 201
    file_id = resp.json()["id"]
    # The original filename is still preserved verbatim for display/download
    # purposes — only the on-disk storage key is sanitized.
    assert resp.json()["filename"] == malicious_name

    with app_engine.begin() as conn:
        storage_key = conn.execute(text("SELECT storage_key FROM file_assets WHERE id = :id"), {"id": file_id}).scalar_one()
    assert storage_key.startswith(f"{org_id}/")
    key_suffix = storage_key.removeprefix(f"{org_id}/")
    assert ".." not in key_suffix
    assert "/" not in key_suffix

    download = client.get(f"/api/v1/files/{file_id}", headers=auth_headers(admin_token))
    assert download.status_code == 200
    assert download.content == b"payload"


def test_html_attachment_is_forced_to_download_not_rendered_inline(client, admin_token, org_id):
    """Security regression: an uploaded file's Content-Type is whatever the
    uploader's client claimed (never validated), so serving it back with
    Content-Disposition: inline would let a same-origin HTML/SVG payload
    execute as a page when a more privileged viewer opens the link —
    including reading this same endpoint's `?token=` query-param auth.
    Only a small safe-to-render allowlist (images/PDF) gets `inline`;
    everything else, including an HTML payload, must download instead."""
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    requirement = _create_requirement(client, admin_token, project["id"], component_id, category_id)

    resp = client.post(
        f"/api/v1/projects/{project['id']}/requirements/{requirement['id']}/files",
        files={"file": ("payload.html", b"<script>alert(document.cookie)</script>", "text/html")},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 201
    file_id = resp.json()["id"]

    download = client.get(f"/api/v1/files/{file_id}", headers=auth_headers(admin_token))
    assert download.status_code == 200
    assert download.headers["content-disposition"].startswith("attachment")
    assert download.headers["x-content-type-options"] == "nosniff"

    # A genuine image still renders inline (no regression for the normal case).
    img_resp = client.post(
        f"/api/v1/projects/{project['id']}/requirements/{requirement['id']}/files",
        files={"file": ("photo.png", b"\x89PNG\r\n\x1a\n", "image/png")},
        headers=auth_headers(admin_token),
    )
    img_download = client.get(f"/api/v1/files/{img_resp.json()['id']}", headers=auth_headers(admin_token))
    assert img_download.headers["content-disposition"].startswith("inline")


def test_project_metrics_includes_file_count(client, admin_token, org_id):
    """U-P-05: the overview metrics' file_count reflects distinct files
    attached to requirements in the project (attachments and linked shared
    resources), not organisation-wide resources in general."""
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    req1 = _create_requirement(client, admin_token, project["id"], component_id, category_id)
    req2 = _create_requirement(client, admin_token, project["id"], component_id, category_id)

    client.post(
        f"/api/v1/projects/{project['id']}/requirements/{req1['id']}/files",
        files={"file": ("a.txt", b"a", "text/plain")}, headers=auth_headers(admin_token),
    )
    client.post(
        f"/api/v1/projects/{project['id']}/requirements/{req2['id']}/files",
        files={"file": ("b.txt", b"b", "text/plain")}, headers=auth_headers(admin_token),
    )

    metrics = client.get(f"/api/v1/projects/{project['id']}/metrics", headers=auth_headers(admin_token)).json()
    assert metrics["file_count"] == 2


def test_non_member_cannot_download_requirement_attachment(client, admin_token, org_id):
    from tests.conftest import create_org_user, login

    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    requirement = _create_requirement(client, admin_token, project["id"], component_id, category_id)
    file_id = client.post(
        f"/api/v1/projects/{project['id']}/requirements/{requirement['id']}/files",
        files={"file": ("spec.txt", b"secret", "text/plain")},
        headers=auth_headers(admin_token),
    ).json()["id"]

    create_org_user(client, admin_token, org_id, "outsider2@example.com", role="member")
    outsider_token = login(client, "outsider2@example.com", "Password123!")

    resp = client.get(f"/api/v1/files/{file_id}", headers=auth_headers(outsider_token))
    assert resp.status_code == 403


def test_org_shared_resource_can_be_linked_to_requirement(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    requirement = _create_requirement(client, admin_token, project["id"], component_id, category_id)

    upload = client.post(
        f"/api/v1/orgs/{org_id}/resources",
        files={"file": ("standard.pdf", b"%PDF-fake", "application/pdf")},
        headers=auth_headers(admin_token),
    )
    assert upload.status_code == 201
    resource_id = upload.json()["id"]

    resources = client.get(f"/api/v1/orgs/{org_id}/resources", headers=auth_headers(admin_token)).json()
    assert any(r["id"] == resource_id for r in resources)

    resp = client.post(
        f"/api/v1/projects/{project['id']}/requirements/{requirement['id']}/files/link",
        json={"file_id": resource_id},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 201

    # Unlinking a shared resource must not delete the underlying shared file.
    client.delete(
        f"/api/v1/projects/{project['id']}/requirements/{requirement['id']}/files/{resource_id}",
        headers=auth_headers(admin_token),
    )
    resources = client.get(f"/api/v1/orgs/{org_id}/resources", headers=auth_headers(admin_token)).json()
    assert any(r["id"] == resource_id for r in resources)


def test_avatar_upload_and_org_logo_upload(client, admin_token, org_id):
    resp = client.post(
        "/api/v1/auth/me/avatar", files={"file": ("me.png", b"\x89PNG", "image/png")}, headers=auth_headers(admin_token)
    )
    assert resp.status_code == 200
    assert resp.json()["avatar_file_id"] is not None

    resp = client.post(
        f"/api/v1/orgs/{org_id}/logo", files={"file": ("logo.png", b"\x89PNG", "image/png")},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 200
    assert resp.json()["logo_file_id"] is not None


def test_org_logo_and_login_background_are_downloadable_with_no_authentication(client, admin_token, org_id):
    """Regression test: the org-branded login page (`/login/{slug}`) renders
    these images before any session exists, so `GET /api/v1/files/{id}` must
    serve them to a fully anonymous caller — not just any authenticated
    user. Previously it required auth unconditionally, so an uploaded login
    background never actually appeared on the real login page."""
    logo = client.post(
        f"/api/v1/orgs/{org_id}/logo", files={"file": ("logo.png", b"\x89PNG", "image/png")},
        headers=auth_headers(admin_token),
    ).json()
    background = client.post(
        f"/api/v1/orgs/{org_id}/login-background", files={"file": ("bg.png", b"\x89PNG", "image/png")},
        headers=auth_headers(admin_token),
    ).json()

    assert client.get(f"/api/v1/files/{logo['logo_file_id']}").status_code == 200
    assert client.get(f"/api/v1/files/{background['login_background_file_id']}").status_code == 200


def test_platform_default_logo_and_login_background_are_downloadable_with_no_authentication(client, admin_token):
    """Same regression as above, for the platform-wide defaults shown on the
    plain `/login` page (no single org's branding applies)."""
    logo = client.post(
        "/api/v1/system/branding/logo", files={"file": ("logo.png", b"\x89PNG", "image/png")},
        headers=auth_headers(admin_token),
    ).json()
    background = client.post(
        "/api/v1/system/branding/login-background", files={"file": ("bg.png", b"\x89PNG", "image/png")},
        headers=auth_headers(admin_token),
    ).json()

    assert client.get(f"/api/v1/files/{logo['default_logo_file_id']}").status_code == 200
    assert client.get(f"/api/v1/files/{background['default_login_background_file_id']}").status_code == 200


def test_system_branding_is_readable_with_no_authentication(client):
    """The plain `/login` page fetches this endpoint before any session
    exists, to pick up the header title and login background file id."""
    resp = client.get("/api/v1/system/branding")
    assert resp.status_code == 200


def test_avatar_and_org_resources_still_require_authentication_when_anonymous(client, admin_token, org_id):
    """Unlike logos/login backgrounds, avatars and org shared resources must
    stay behind authentication — the anonymous carve-out above is narrowly
    scoped to public branding images only."""
    avatar = client.post(
        "/api/v1/auth/me/avatar", files={"file": ("me.png", b"\x89PNG", "image/png")}, headers=auth_headers(admin_token)
    ).json()
    assert client.get(f"/api/v1/files/{avatar['avatar_file_id']}").status_code == 401

    resource = client.post(
        f"/api/v1/orgs/{org_id}/resources", files={"file": ("doc.txt", b"hello", "text/plain")},
        headers=auth_headers(admin_token),
    ).json()
    assert client.get(f"/api/v1/files/{resource['id']}").status_code == 401
