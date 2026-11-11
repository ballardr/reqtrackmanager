"""Hardening of project bundle import: people named in a bundle must belong to the target organisation, a bundle cannot
forge who did something, and an organisation can refuse imported approval state."""

from __future__ import annotations

from sqlalchemy import select

from app.database import SessionLocal
from app.models.audit import AuditEvent
from app.models.user import User
from tests.conftest import auth_headers, create_org_admin_in
from tests.test_project_export_import import _build_rich_project


def _import(client, token, org_id, bundle, name="Imported"):
    return client.post(
        "/api/v1/projects/import",
        data={"organization_id": org_id, "name": name},
        files={"file": ("bundle.zip", bundle, "application/zip")},
        headers=auth_headers(token),
    )


def test_a_person_outside_the_target_organisation_becomes_an_imported_person(client, admin_token, org_id):
    project, _, _ = _build_rich_project(client, admin_token, org_id)
    bundle = client.get(f"/api/v1/projects/{project['id']}/export", headers=auth_headers(admin_token)).content
    other_org, other_admin = create_org_admin_in(client, admin_token, "Strict Target")

    result = _import(client, other_admin, other_org["id"], bundle).json()

    assert any("imported person" in w for w in result["warnings"])
    requirements = client.get(
        f"/api/v1/projects/{result['project']['id']}/requirements", headers=auth_headers(other_admin)
    ).json()
    assert requirements
    me = client.get("/api/v1/auth/me", headers=auth_headers(other_admin)).json()["id"]
    creators = {r["creator_id"] for r in requirements}
    assert me not in creators
    db = SessionLocal()
    try:
        for creator in creators:
            user = db.get(User, creator)
            assert user is not None and str(user.imported_organization_id) == other_org["id"]
            assert not user.is_active and user.is_archived and user.password_hash is None
            assert user.email.endswith("@imported.example.com") and "admin@example.com" not in user.email
    finally:
        db.close()


def test_replayed_history_is_attributed_to_an_imported_person_and_marked_as_imported(client, admin_token, org_id):
    project, _, _ = _build_rich_project(client, admin_token, org_id)
    bundle = client.get(f"/api/v1/projects/{project['id']}/export", headers=auth_headers(admin_token)).content
    other_org, other_admin = create_org_admin_in(client, admin_token, "History Target")
    new_id = _import(client, other_admin, other_org["id"], bundle).json()["project"]["id"]
    importer = client.get("/api/v1/auth/me", headers=auth_headers(other_admin)).json()["id"]

    db = SessionLocal()
    try:
        replayed = [
            e for e in db.scalars(select(AuditEvent).where(AuditEvent.project_id == new_id))
            if isinstance(e.detail, dict) and "imported_from_bundle" in e.detail
        ]
        assert replayed, "the source project's structural history should be replayed"
        assert importer not in {str(e.actor_id) for e in replayed}
        for e in replayed:
            actor = db.get(User, e.actor_id)
            assert actor is not None and actor.imported_organization_id is not None
            origin = e.detail["imported_from_bundle"]
            assert origin["imported_by"] == importer and origin["imported_at"] and origin["original_actor_name"]
            assert "original_actor_email" not in origin
        counted = db.scalar(
            select(AuditEvent).where(AuditEvent.project_id == new_id, AuditEvent.action == "imported_from_bundle")
        )
        assert counted is not None and counted.detail["records_with_approval_state"] >= 2
    finally:
        db.close()


def test_an_organisation_can_refuse_imported_approval_state(client, admin_token, org_id):
    project, _, _ = _build_rich_project(client, admin_token, org_id)
    bundle = client.get(f"/api/v1/projects/{project['id']}/export", headers=auth_headers(admin_token)).content
    other_org, other_admin = create_org_admin_in(client, admin_token, "No Approvals Target")
    settings = client.get(f"/api/v1/orgs/{other_org['id']}/advanced-settings", headers=auth_headers(other_admin))
    assert settings.json()["allow_imported_approval_state"] is True
    body = {**settings.json(), "allow_imported_approval_state": False}
    body.pop("smtp_password", None)
    saved = client.put(f"/api/v1/orgs/{other_org['id']}/advanced-settings", json=body, headers=auth_headers(other_admin))
    assert saved.status_code == 200, saved.text
    assert saved.json()["allow_imported_approval_state"] is False

    result = _import(client, other_admin, other_org["id"], bundle).json()
    new_id = result["project"]["id"]

    assert any("does not keep imported approval state" in w for w in result["warnings"])
    requirements = client.get(f"/api/v1/projects/{new_id}/requirements", headers=auth_headers(other_admin)).json()
    assert requirements and {r["status"] for r in requirements} == {"draft"}
    assert not any(r["is_completed"] for r in requirements)
    change_requests = client.get(f"/api/v1/projects/{new_id}/change-requests", headers=auth_headers(other_admin)).json()
    assert change_requests and {c["status"] for c in change_requests} == {"draft"}
    votes = client.get(
        f"/api/v1/projects/{new_id}/change-requests/{change_requests[0]['id']}/votes", headers=auth_headers(other_admin)
    ).json()
    assert votes["approve_count"] == 0


def _zip(entries: dict[str, bytes], *, compress: bool = True) -> bytes:
    import io
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED if compress else zipfile.ZIP_STORED) as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return buffer.getvalue()


def test_a_bundle_with_too_many_entries_is_refused(client, admin_token, org_id, monkeypatch):
    from app.services import bundle_common

    monkeypatch.setattr(bundle_common, "MAX_BUNDLE_ENTRIES", 3)
    bundle = _zip({f"files/{i}": b"x" for i in range(5)})
    assert _import(client, admin_token, org_id, bundle).status_code == 413


def test_a_bundle_that_compresses_suspiciously_well_is_refused(client, admin_token, org_id):
    bundle = _zip({"manifest.json": b"{}", "project.json": b"0" * (8 * 1024 * 1024)})
    resp = _import(client, admin_token, org_id, bundle)
    assert resp.status_code == 413
    assert "suspiciously" in resp.json()["detail"]


def test_a_json_entry_over_the_cap_is_refused_whatever_its_header_says(client, admin_token, org_id, monkeypatch):
    from app.services import bundle_common

    monkeypatch.setattr(bundle_common, "MAX_BUNDLE_JSON_BYTES", 10)
    bundle = _zip({"manifest.json": b'{"kind": "project-export", "padding": "' + b"x" * 100 + b'"}', "project.json": b"{}"})
    assert _import(client, admin_token, org_id, bundle).status_code == 413


def test_a_corrupt_entry_is_a_bad_request_not_a_server_error(client, admin_token, org_id):
    bundle = bytearray(_zip({"manifest.json": b'{"kind": "project-export"}' * 20, "project.json": b"{}"}, compress=False))
    at = bytes(bundle).index(b'{"kind"')
    bundle[at + 3] ^= 0xFF  # flips a byte inside the stored data, so the CRC no longer matches
    resp = _import(client, admin_token, org_id, bytes(bundle))
    assert resp.status_code == 400


def test_an_image_claim_must_match_the_bytes():
    import io

    from PIL import Image

    from app.services.files import trusted_content_type

    png = io.BytesIO()
    Image.new("RGB", (2, 2)).save(png, "PNG")
    jpeg = io.BytesIO()
    Image.new("RGB", (2, 2)).save(jpeg, "JPEG")
    assert trusted_content_type("image/jpeg", png.getvalue()) == "image/png"
    assert trusted_content_type("text/html", png.getvalue()) == "text/html"  # only an image claim is checked
    assert trusted_content_type("image/png", b"<html><script>1</script></html>") == "application/octet-stream"
    assert trusted_content_type("image/svg+xml", b'<?xml version="1.0"?><svg xmlns="x"/>') == "image/svg+xml"
    assert trusted_content_type("image/svg+xml", b"not svg") == "application/octet-stream"
    assert trusted_content_type("", b"x") == "application/octet-stream"
