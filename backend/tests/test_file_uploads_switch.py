"""Deployment-wide file upload switch: disabling stops every new user file at the one server-side gate, leaves existing
files readable and deletable, is server-administrator only and audited, and an import brings its files whenever they can be
stored (otherwise the call is refused before any row is written, or goes ahead without files when `skip_files` is set)."""

import re
from pathlib import Path

from sqlalchemy import select

from app.database import SessionLocal
from app.models.audit import AuditEvent
from app.models.file import FileAsset
from app.models.project import Project
from tests.conftest import (
    auth_headers,
    create_component_and_category,
    create_org_user,
    create_project,
    login,
)

SWITCH = "/api/v1/system/file-uploads"


def _set_uploads(client, token: str, enabled: bool):
    return client.put(SWITCH, json={"file_uploads_enabled": enabled}, headers=auth_headers(token))


def _requirement_with_file(client, token: str, org_id: str) -> tuple[dict, str, str]:
    project = create_project(client, token, org_id)
    component_id, category_id = create_component_and_category(client, token, project["id"])
    requirement = client.post(
        f"/api/v1/projects/{project['id']}/requirements",
        json={"name": "Req", "component_id": component_id, "category_id": category_id}, headers=auth_headers(token),
    ).json()
    uploaded = client.post(
        f"/api/v1/projects/{project['id']}/requirements/{requirement['id']}/files",
        files={"file": ("spec.txt", b"hello world", "text/plain")}, headers=auth_headers(token),
    )
    assert uploaded.status_code == 201, uploaded.text
    return project, requirement["id"], uploaded.json()["id"]


def _import(client, token: str, org_id: str, bundle: bytes, name: str, **extra):
    return client.post(
        "/api/v1/projects/import", data={"organization_id": org_id, "name": name, **extra},
        files={"file": ("bundle.zip", bundle, "application/zip")}, headers=auth_headers(token),
    )


def test_uploads_are_enabled_by_default_and_the_public_read_says_so(client):
    assert client.get("/api/v1/system/branding").json()["file_uploads_enabled"] is True


def test_only_a_server_administrator_may_change_the_switch(client, admin_token, org_id):
    create_org_user(client, admin_token, org_id, "plain@example.com")
    member = login(client, "plain@example.com", "Password123!")
    assert _set_uploads(client, member, False).status_code == 403
    assert client.get("/api/v1/system/branding").json()["file_uploads_enabled"] is True
    assert client.put(SWITCH, json={"file_uploads_enabled": False}).status_code in (401, 403)


def test_the_change_is_audited_with_the_value_only(client, admin_token):
    assert _set_uploads(client, admin_token, False).status_code == 200
    assert client.get("/api/v1/system/branding").json()["file_uploads_enabled"] is False
    with SessionLocal() as db:
        event = db.scalars(select(AuditEvent).where(AuditEvent.action == "file_uploads_updated")).one()
        assert event.detail == {"file_uploads_enabled": False}
    _set_uploads(client, admin_token, True)


def test_every_family_of_upload_is_refused_while_disabled(client, admin_token, org_id):
    project, requirement_id, _ = _requirement_with_file(client, admin_token, org_id)
    assert _set_uploads(client, admin_token, False).status_code == 200
    try:
        attempts = [
            client.post(
                f"/api/v1/projects/{project['id']}/requirements/{requirement_id}/files",
                files={"file": ("a.txt", b"x", "text/plain")}, headers=auth_headers(admin_token),
            ),
            client.post(
                f"/api/v1/orgs/{org_id}/resources", files={"file": ("r.txt", b"x", "text/plain")},
                headers=auth_headers(admin_token),
            ),
            client.post(
                "/api/v1/auth/me/avatar", files={"file": ("me.png", b"\x89PNG", "image/png")},
                headers=auth_headers(admin_token),
            ),
            client.post(
                "/api/v1/system/branding/image", data={"kind": "logo"},
                files={"file": ("l.png", b"\x89PNG", "image/png")}, headers=auth_headers(admin_token),
            ),
        ]
        for response in attempts:
            assert response.status_code == 403, response.text
            assert response.json()["detail"]["code"] == "uploads_disabled"
    finally:
        _set_uploads(client, admin_token, True)


def test_existing_files_stay_readable_and_deletable_while_disabled(client, admin_token, org_id):
    project, requirement_id, file_id = _requirement_with_file(client, admin_token, org_id)
    _set_uploads(client, admin_token, False)
    try:
        assert client.get(f"/api/v1/files/{file_id}", headers=auth_headers(admin_token)).content == b"hello world"
        deleted = client.delete(
            f"/api/v1/projects/{project['id']}/requirements/{requirement_id}/files/{file_id}",
            headers=auth_headers(admin_token),
        )
        assert deleted.status_code == 204
    finally:
        _set_uploads(client, admin_token, True)


def test_import_without_skip_files_is_refused_before_any_row_is_written(client, admin_token, org_id):
    project, _, _ = _requirement_with_file(client, admin_token, org_id)
    bundle = client.get(f"/api/v1/projects/{project['id']}/export", headers=auth_headers(admin_token)).content
    _set_uploads(client, admin_token, False)
    try:
        refused = _import(client, admin_token, org_id, bundle, "Refused copy")
        assert refused.status_code == 403, refused.text
        detail = refused.json()["detail"]
        assert detail["code"] == "uploads_disabled" and detail["file_count"] == 1 and detail["file_bytes"] == len(b"hello world")
        with SessionLocal() as db:
            assert db.scalar(select(Project).where(Project.name == "Refused copy")) is None
    finally:
        _set_uploads(client, admin_token, True)


def test_import_with_skip_files_creates_the_records_without_files_and_reports_the_count(client, admin_token, org_id):
    project, _, _ = _requirement_with_file(client, admin_token, org_id)
    bundle = client.get(f"/api/v1/projects/{project['id']}/export", headers=auth_headers(admin_token)).content
    with SessionLocal() as db:
        files_before = len(db.scalars(select(FileAsset)).all())
    _set_uploads(client, admin_token, False)
    try:
        imported = _import(client, admin_token, org_id, bundle, "Skipped files", skip_files="true")
        assert imported.status_code == 201, imported.text
        assert any("1 file" in w and "not imported" in w for w in imported.json()["warnings"])
        with SessionLocal() as db:
            assert len(db.scalars(select(FileAsset)).all()) == files_before
        new_id = imported.json()["project"]["id"]
        listed = client.get(f"/api/v1/projects/{new_id}/requirements", headers=auth_headers(admin_token)).json()
        assert len(listed) == 1
    finally:
        _set_uploads(client, admin_token, True)


def test_files_are_imported_while_allowed_and_skip_files_is_ignored(client, admin_token, org_id):
    project, _, _ = _requirement_with_file(client, admin_token, org_id)
    bundle = client.get(f"/api/v1/projects/{project['id']}/export", headers=auth_headers(admin_token)).content
    with SessionLocal() as db:
        files_before = len(db.scalars(select(FileAsset)).all())
    imported = _import(client, admin_token, org_id, bundle, "Kept files", skip_files="true")
    assert imported.status_code == 201, imported.text
    assert not any("not imported" in w for w in imported.json()["warnings"])
    with SessionLocal() as db:
        assert len(db.scalars(select(FileAsset)).all()) == files_before + 1


def test_a_bundle_without_files_imports_while_disabled(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    bundle = client.get(f"/api/v1/projects/{project['id']}/export", headers=auth_headers(admin_token)).content
    _set_uploads(client, admin_token, False)
    try:
        assert _import(client, admin_token, org_id, bundle, "No files").status_code == 201
    finally:
        _set_uploads(client, admin_token, True)


def test_every_storage_writer_is_gated():
    """A new place that writes bytes to storage must go through `upload_file` (and so the gate) or be listed here with
    its reason. Fix the code, not this test."""
    app_dir = Path(__file__).resolve().parent.parent / "app"
    exempt = {
        "services/files.py": "the gate and the one writer",
        "services/storage_health.py": "the monitor's own probe object, not a user file",
        "services/report_run_jobs.py": "generated report outputs, not uploads",
    }
    writers = set()
    for path in app_dir.rglob("*.py"):
        rel = path.relative_to(app_dir).as_posix()
        if "/tests/" in rel or rel.startswith("storage_backends/"):
            continue
        if re.search(r"(get_storage_backend\(\)|\bbackend)\.save\(", path.read_text()):
            writers.add(rel)
    assert writers == set(exempt), f"unlisted storage writers: {sorted(writers - set(exempt))}"
    source = (app_dir / "services/files.py").read_text()
    body = source.split("def upload_file(", 1)[1].split("backend.save(", 1)[0]
    assert "assert_uploads_allowed(db, organization_id)" in body
