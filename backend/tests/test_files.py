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


def test_delete_org_logo_and_login_background_revert_to_the_platform_default(client, admin_token, org_id):
    """UX audit finding: logo and login background had no revert path at
    all, in the UI or the API — unlike the text-based branding overrides
    (`OverridePill`). These new `DELETE` endpoints close that gap: clearing
    the override falls back to the platform default (`GET /system/branding`)
    the same way a null `header_title`/`email_footer_*` already does, and
    the now-orphaned file is actually removed from storage, not just
    unlinked — matching `delete_org_resource`'s cleanup."""
    logo = client.post(
        f"/api/v1/orgs/{org_id}/logo", files={"file": ("logo.png", b"\x89PNG", "image/png")},
        headers=auth_headers(admin_token),
    ).json()
    background = client.post(
        f"/api/v1/orgs/{org_id}/login-background", files={"file": ("bg.png", b"\x89PNG", "image/png")},
        headers=auth_headers(admin_token),
    ).json()
    logo_file_id = logo["logo_file_id"]
    background_file_id = background["login_background_file_id"]

    delete_logo = client.delete(f"/api/v1/orgs/{org_id}/logo", headers=auth_headers(admin_token))
    assert delete_logo.status_code == 200
    assert delete_logo.json()["logo_file_id"] is None
    assert client.get(f"/api/v1/files/{logo_file_id}").status_code == 404

    delete_background = client.delete(f"/api/v1/orgs/{org_id}/login-background", headers=auth_headers(admin_token))
    assert delete_background.status_code == 200
    assert delete_background.json()["login_background_file_id"] is None
    assert client.get(f"/api/v1/files/{background_file_id}").status_code == 404


def test_delete_org_logo_is_a_noop_when_nothing_is_set(client, admin_token, org_id):
    """Reverting a setting that's already at the platform default is a
    legitimate no-op (200, unchanged), not a 404 — this isn't deleting a
    specific known record, it's asserting an end state that may already
    hold."""
    resp = client.delete(f"/api/v1/orgs/{org_id}/logo", headers=auth_headers(admin_token))
    assert resp.status_code == 200
    assert resp.json()["logo_file_id"] is None


def test_org_member_cannot_delete_org_logo(client, admin_token, org_id):
    from tests.conftest import create_org_user, login

    client.post(
        f"/api/v1/orgs/{org_id}/logo", files={"file": ("logo.png", b"\x89PNG", "image/png")},
        headers=auth_headers(admin_token),
    )
    create_org_user(client, admin_token, org_id, "logo-member@example.com", role="member")
    member_token = login(client, "logo-member@example.com", "Password123!")

    resp = client.delete(f"/api/v1/orgs/{org_id}/logo", headers=auth_headers(member_token))
    assert resp.status_code == 403


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


def test_project_files_endpoint_combines_sources_and_scopes_by_project(client, admin_token, org_id):
    """GET /projects/{id}/files (gap docs/requirements.md U-P-05 anticipated
    but left unspec'd — file_count was a metric only) must combine files
    reachable via all three join tables — a direct requirement attachment
    (RequirementFile), a requirement action attachment
    (RequirementActionFile), and a comment attachment (CommentFile) — into
    one project-scoped list, each row carrying its originating context.

    Critically also asserts same-target-scoped resolution (a hard
    access-control-policy requirement, not "has access somewhere"): a file
    belonging to a *different* project, uploaded by the same caller who has
    full access to both projects, must never appear in this project's file
    list.
    """
    project = create_project(client, admin_token, org_id, name="Files Project")
    other_project = create_project(client, admin_token, org_id, name="Other Files Project")
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    other_component_id, other_category_id = create_component_and_category(client, admin_token, other_project["id"])

    req1 = _create_requirement(client, admin_token, project["id"], component_id, category_id)
    req2 = _create_requirement(client, admin_token, project["id"], component_id, category_id)
    other_req = _create_requirement(client, admin_token, other_project["id"], other_component_id, other_category_id)

    # 1. Direct requirement attachment.
    direct_upload = client.post(
        f"/api/v1/projects/{project['id']}/requirements/{req1['id']}/files",
        files={"file": ("direct.txt", b"direct", "text/plain")}, headers=auth_headers(admin_token),
    )
    assert direct_upload.status_code == 201, direct_upload.text
    direct_file_id = direct_upload.json()["id"]

    # 2. Requirement action attachment.
    action_type_id = client.get(
        f"/api/v1/projects/{project['id']}/action-types", headers=auth_headers(admin_token)
    ).json()[0]["id"]
    action = client.post(
        f"/api/v1/projects/{project['id']}/actions",
        json={"title": "Review the spec", "action_type_id": action_type_id}, headers=auth_headers(admin_token),
    ).json()
    action_upload = client.post(
        f"/api/v1/projects/{project['id']}/actions/{action['id']}/files",
        files={"file": ("action.pdf", b"action", "application/pdf")}, headers=auth_headers(admin_token),
    )
    assert action_upload.status_code == 201, action_upload.text
    action_file_id = action_upload.json()["id"]

    # 3. Comment attachment on a different requirement in the same project.
    comment = client.post(
        f"/api/v1/projects/{project['id']}/requirements/{req2['id']}/comments",
        json={"body": "See attached"}, headers=auth_headers(admin_token),
    ).json()
    comment_upload = client.post(
        f"/api/v1/projects/{project['id']}/requirements/{req2['id']}/comments/{comment['id']}/files",
        files={"file": ("comment.txt", b"comment", "text/plain")}, headers=auth_headers(admin_token),
    )
    assert comment_upload.status_code == 201, comment_upload.text
    comment_file_id = comment_upload.json()["id"]

    # A file in the *other* project — must never leak into `project`'s list.
    other_upload = client.post(
        f"/api/v1/projects/{other_project['id']}/requirements/{other_req['id']}/files",
        files={"file": ("other.txt", b"other", "text/plain")}, headers=auth_headers(admin_token),
    )
    assert other_upload.status_code == 201, other_upload.text
    other_file_id = other_upload.json()["id"]

    resp = client.get(f"/api/v1/projects/{project['id']}/files", headers=auth_headers(admin_token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert resp.headers["x-total-count"] == "3"
    assert len(body) == 3

    by_id = {row["file"]["id"]: row for row in body}
    assert set(by_id.keys()) == {direct_file_id, action_file_id, comment_file_id}
    assert other_file_id not in by_id

    direct_row = by_id[direct_file_id]
    assert direct_row["source"] == "requirement_attachment"
    assert direct_row["requirement_id"] == req1["id"]
    assert direct_row["requirement_unique_code"] == req1["unique_code"]
    assert direct_row["action_id"] is None
    assert direct_row["uploaded_by_display_name"]

    action_row = by_id[action_file_id]
    assert action_row["source"] == "action_attachment"
    assert action_row["action_id"] == action["id"]
    assert action_row["action_unique_code"] == action["unique_code"]
    assert action_row["requirement_id"] is None

    comment_row = by_id[comment_file_id]
    assert comment_row["source"] == "comment_attachment"
    assert comment_row["requirement_id"] == req2["id"]
    assert comment_row["comment_id"] == comment["id"]


def test_project_files_endpoint_requires_project_membership(client, admin_token, org_id):
    """Matches every other project-content endpoint's `require_project_view`
    behaviour: a user with no role on the project at all is denied (not
    just filtered to an empty list)."""
    from tests.conftest import create_org_user, login

    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    requirement = _create_requirement(client, admin_token, project["id"], component_id, category_id)
    client.post(
        f"/api/v1/projects/{project['id']}/requirements/{requirement['id']}/files",
        files={"file": ("spec.txt", b"secret", "text/plain")}, headers=auth_headers(admin_token),
    )

    create_org_user(client, admin_token, org_id, "files-outsider@example.com", role="member")
    outsider_token = login(client, "files-outsider@example.com", "Password123!")

    resp = client.get(f"/api/v1/projects/{project['id']}/files", headers=auth_headers(outsider_token))
    assert resp.status_code == 403


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
