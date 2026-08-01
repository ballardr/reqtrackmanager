"""Tests for file storage (I-M-10): requirement attachments (C-M-02), org
shared resources (C-M-03), linking a shared resource to a requirement
(C-M-04), and avatar/logo upload (C-U-18, U-C-02)."""

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
