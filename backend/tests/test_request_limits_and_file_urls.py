"""Tests for the request-size ceilings, the safe download filename, and the credential a file URL carries.

- No request may be larger than its ceiling (`body_limit`, `Settings.max_upload_bytes`), so a signed-in user
  with the lowest upload right cannot exhaust a worker's memory.
- A file's stored name can be anything the uploader chose; the download header must stay valid for it.
- A file URL (`<img src>`) cannot send an Authorization header, so it carries a credential in the query
  string. That credential is a short-lived media token, never the session token or a PAT.
"""

import pytest

from app.config import get_settings
from app.services import files as files_service
from tests.conftest import auth_headers, create_component_and_category, create_project, media_token


def _requirement_with_file(client, token, org_id, *, filename="spec.txt", content=b"hello", content_type="text/plain"):
    """Creates a project and requirement and attaches a file; returns `(file_id, project_id)`."""
    project = create_project(client, token, org_id)
    component_id, category_id = create_component_and_category(client, token, project["id"])
    requirement = client.post(
        f"/api/v1/projects/{project['id']}/requirements",
        json={"name": "Req", "component_id": component_id, "category_id": category_id},
        headers=auth_headers(token),
    ).json()
    resp = client.post(
        f"/api/v1/projects/{project['id']}/requirements/{requirement['id']}/files",
        files={"file": (filename, content, content_type)}, headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"], project["id"]


def test_an_upload_over_the_file_limit_is_refused_and_stores_nothing(client, admin_token, org_id, monkeypatch):
    # The module-level settings object the code under test holds, which a test elsewhere may have replaced
    # `get_settings()`'s cached instance of.
    monkeypatch.setattr(files_service.settings, "max_upload_bytes", 1024)
    resp = client.post(
        "/api/v1/auth/me/avatar", files={"file": ("big.png", b"x" * 2048, "image/png")}, headers=auth_headers(admin_token),
    )
    assert resp.status_code == 413, resp.text
    assert client.get("/api/v1/auth/me", headers=auth_headers(admin_token)).json()["avatar_file_id"] is None


def test_a_request_body_over_the_general_ceiling_is_refused_before_it_is_read(client, admin_token, monkeypatch):
    monkeypatch.setattr(get_settings(), "max_request_body_bytes", 100)
    headers = {**auth_headers(admin_token), "Content-Type": "application/json"}
    resp = client.post("/api/v1/projects", content=b"{" + b" " * 500 + b"}", headers=headers)
    assert resp.status_code == 413
    assert "too large" in resp.json()["detail"]


def test_import_endpoints_keep_their_larger_ceiling(client, admin_token, monkeypatch):
    """An import is allowed far more than the general ceiling; the request reaches the handler (which rejects
    the junk file for its own reasons) instead of being cut off by the body limit."""
    monkeypatch.setattr(get_settings(), "max_request_body_bytes", 100)
    resp = client.post(
        "/api/v1/orgs/import", files={"file": ("bundle.zip", b"not a zip" * 100, "application/zip")}, headers=auth_headers(admin_token),
    )
    assert resp.status_code != 413


def test_a_non_latin_filename_downloads_instead_of_crashing(client, admin_token, org_id):
    file_id, _ = _requirement_with_file(client, admin_token, org_id, filename='文档 "final".txt')
    resp = client.get(f"/api/v1/files/{file_id}", headers=auth_headers(admin_token))
    assert resp.status_code == 200
    disposition = resp.headers["content-disposition"]
    assert disposition.startswith("attachment;") and "filename*=UTF-8''" in disposition
    assert '"final"' not in disposition.split("filename*")[0]


class TestFileUrlCredential:
    """What `?token=` may carry on a file URL."""

    def test_a_media_token_loads_a_file_and_the_session_token_in_the_url_does_not(self, client, admin_token, org_id):
        file_id, _ = _requirement_with_file(client, admin_token, org_id)
        ok = client.get(f"/api/v1/files/{file_id}", params={"token": media_token(client, admin_token)})
        assert ok.status_code == 200 and ok.content == b"hello"
        assert client.get(f"/api/v1/files/{file_id}", params={"token": admin_token}).status_code == 401

    def test_a_pat_in_the_url_is_refused(self, client, admin_token, org_id):
        file_id, _ = _requirement_with_file(client, admin_token, org_id)
        pat = client.post(
            "/api/v1/me/pats", json={"name": "t", "allowed_organization_ids": [org_id]}, headers=auth_headers(admin_token),
        ).json()["token"]
        assert client.get(f"/api/v1/files/{file_id}", params={"token": pat}).status_code == 401
        # In the header it still works: that is the supported way for a script.
        assert client.get(f"/api/v1/files/{file_id}", headers=auth_headers(pat)).status_code == 200

    def test_a_media_token_is_good_for_nothing_else(self, client, admin_token):
        token = media_token(client, admin_token)
        assert client.get("/api/v1/auth/me", headers=auth_headers(token)).status_code == 401

    def test_a_media_token_dies_with_the_next_credential_change(self, client, admin_token, org_id):
        file_id, _ = _requirement_with_file(client, admin_token, org_id)
        token = media_token(client, admin_token)
        changed = client.post(
            "/api/v1/auth/change-password",
            json={"current_password": "ChangeMe123!", "new_password": "NewPassword123!"}, headers=auth_headers(admin_token),
        )
        assert changed.status_code == 204
        assert client.get(f"/api/v1/files/{file_id}", params={"token": token}).status_code == 401

    def test_only_a_session_can_mint_one(self, client, admin_token, org_id):
        pat = client.post(
            "/api/v1/me/pats", json={"name": "t", "allowed_organization_ids": [org_id]}, headers=auth_headers(admin_token),
        ).json()["token"]
        assert client.post("/api/v1/auth/media-token", headers=auth_headers(pat)).status_code == 403
        assert client.post("/api/v1/auth/media-token").status_code == 401

    @pytest.mark.parametrize("path", ["/api/v1/auth/me"])
    def test_a_session_token_in_a_query_string_authenticates_nothing(self, client, admin_token, path):
        assert client.get(path, params={"token": admin_token}).status_code == 401
