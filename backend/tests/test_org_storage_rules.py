"""An organisation's own upload switch and storage limit: set only by a server administrator or a Platform subscription
manager, enforced at the one upload gate with distinct codes, race-safe, measured by the same figure the usage table shows,
and never affecting another organisation. Existing files stay readable and deletable whatever the limit."""

import threading
import time
import uuid

from sqlalchemy import select

from app.database import SessionLocal
from app.models.audit import AuditEvent
from app.models.file import FileAsset
from app.models.generated_report import GeneratedReport
from app.models.notification import Notification
from app.models.organization import Organization
from app.models.user import User
from app.services import storage_usage
from tests.conftest import (
    auth_headers,
    create_component_and_category,
    create_org_admin_in,
    create_org_user,
    create_project,
    login,
)

MANAGER = "subscription_manager"


def _storage(org_id: str) -> str:
    return f"/api/v1/orgs/{org_id}/storage"


def _put(client, token, org_id, *, enabled=True, quota=None):
    return client.put(
        _storage(org_id), json={"file_uploads_enabled": enabled, "storage_quota_bytes": quota}, headers=auth_headers(token),
    )


def _manager(client, admin_token, org_id, email="manager@example.com") -> str:
    user_id = create_org_user(client, admin_token, org_id, email, role="member")
    granted = client.post(
        f"/api/v1/system/users/{user_id}/server-roles", json={"role": MANAGER}, headers=auth_headers(admin_token),
    )
    assert granted.status_code == 204, granted.text
    return login(client, email, "Password123!")


def _requirement(client, token, org_id) -> tuple[str, str]:
    project = create_project(client, token, org_id)
    component_id, category_id = create_component_and_category(client, token, project["id"])
    requirement = client.post(
        f"/api/v1/projects/{project['id']}/requirements",
        json={"name": "Req", "component_id": component_id, "category_id": category_id}, headers=auth_headers(token),
    ).json()
    return project["id"], requirement["id"]


def _upload(client, token, project_id, requirement_id, data: bytes):
    return client.post(
        f"/api/v1/projects/{project_id}/requirements/{requirement_id}/files",
        files={"file": ("f.bin", data, "application/octet-stream")}, headers=auth_headers(token),
    )


def _notified(org_id: str) -> int:
    with SessionLocal() as db:
        return len(db.scalars(
            select(Notification).where(Notification.type == "storage_limit_near", Notification.entity_id == org_id)
        ).all())


# --- who may read and change it ---------------------------------------------------------------------------------


def test_defaults_are_enabled_and_unlimited(client, admin_token):
    org, org_admin = create_org_admin_in(client, admin_token, "Defaults Org")
    body = client.get(_storage(org["id"]), headers=auth_headers(org_admin)).json()
    assert body["file_uploads_enabled"] is True and body["deployment_uploads_enabled"] is True
    assert body["storage_quota_bytes"] is None and body["effective_quota_bytes"] is None and body["quota_source"] is None
    assert body["used_bytes"] == 0 and body["file_count"] == 0 and body["warning"] is False
    assert body["can_edit"] is False


def test_an_organisation_administrator_reads_but_cannot_write(client, admin_token):
    org, org_admin = create_org_admin_in(client, admin_token, "Cannot Lift")
    assert _put(client, org_admin, org["id"], quota=10).status_code == 403
    assert _put(client, org_admin, org["id"], enabled=False).status_code == 403
    assert client.get(_storage(org["id"]), headers=auth_headers(org_admin)).json()["storage_quota_bytes"] is None


def test_a_member_and_an_outsider_cannot_read_or_write(client, admin_token):
    org, _ = create_org_admin_in(client, admin_token, "Closed One")
    _, outsider = create_org_admin_in(client, admin_token, "Closed Two")
    create_org_user(client, admin_token, org["id"], "plain-member@example.com")
    member = login(client, "plain-member@example.com", "Password123!")
    for token in (member, outsider):
        assert client.get(_storage(org["id"]), headers=auth_headers(token)).status_code == 403
        assert _put(client, token, org["id"], quota=1).status_code == 403


def test_a_platform_subscription_manager_and_a_server_administrator_may_write(client, admin_token):
    org, _ = create_org_admin_in(client, admin_token, "Operator Org")
    manager = _manager(client, admin_token, org["id"])
    read = client.get(_storage(org["id"]), headers=auth_headers(manager))
    assert read.status_code == 200 and read.json()["can_edit"] is True
    assert _put(client, manager, org["id"], quota=1000).status_code == 200
    assert _put(client, admin_token, org["id"], quota=2000).json()["storage_quota_bytes"] == 2000


def test_a_removal_authority_alone_cannot_change_storage_rules(client, admin_token):
    org, _ = create_org_admin_in(client, admin_token, "Removal Org")
    user_id = create_org_user(client, admin_token, org["id"], "remover@example.com")
    client.post(
        f"/api/v1/system/users/{user_id}/server-roles", json={"role": "subscription_removal_authority"},
        headers=auth_headers(admin_token),
    )
    remover = login(client, "remover@example.com", "Password123!")
    assert _put(client, remover, org["id"], quota=1).status_code == 403
    assert client.get(_storage(org["id"]), headers=auth_headers(remover)).status_code == 403


def test_a_change_is_audited_with_old_and_new_values_and_the_role_and_no_file_data(client, admin_token):
    org, _ = create_org_admin_in(client, admin_token, "Audit Org")
    assert _put(client, admin_token, org["id"], enabled=False, quota=5000).status_code == 200
    with SessionLocal() as db:
        event = db.scalars(
            select(AuditEvent).where(AuditEvent.action == "storage_rules_updated", AuditEvent.entity_id == org["id"])
        ).one()
        assert event.organization_id == uuid.UUID(org["id"])
        assert event.detail["role_used"] == "server_admin"
        assert event.detail["before"] == {"file_uploads_enabled": True, "storage_quota_bytes": None}
        assert event.detail["after"] == {"file_uploads_enabled": False, "storage_quota_bytes": 5000}


def test_a_negative_limit_is_rejected(client, admin_token):
    org, _ = create_org_admin_in(client, admin_token, "Negative Org")
    assert _put(client, admin_token, org["id"], quota=-1).status_code == 422


# --- the switch --------------------------------------------------------------------------------------------------


def test_the_organisation_switch_refuses_that_organisation_only_and_keeps_existing_files(client, admin_token):
    first, first_admin = create_org_admin_in(client, admin_token, "Switch One")
    second, second_admin = create_org_admin_in(client, admin_token, "Switch Two")
    p1, r1 = _requirement(client, first_admin, first["id"])
    p2, r2 = _requirement(client, second_admin, second["id"])
    existing = _upload(client, first_admin, p1, r1, b"keep me")
    assert existing.status_code == 201
    assert _put(client, admin_token, first["id"], enabled=False).status_code == 200
    refused = _upload(client, first_admin, p1, r1, b"x")
    assert refused.status_code == 403 and refused.json()["detail"]["code"] == "organization_uploads_disabled"
    assert _upload(client, second_admin, p2, r2, b"x").status_code == 201
    file_id = existing.json()["id"]
    assert client.get(f"/api/v1/files/{file_id}", headers=auth_headers(first_admin)).content == b"keep me"
    deleted = client.delete(f"/api/v1/projects/{p1}/requirements/{r1}/files/{file_id}", headers=auth_headers(first_admin))
    assert deleted.status_code == 204
    assert _put(client, admin_token, first["id"], enabled=True).status_code == 200
    assert _upload(client, first_admin, p1, r1, b"x").status_code == 201


def test_the_deployment_switch_takes_precedence_and_reports_its_own_code(client, admin_token):
    org, org_admin = create_org_admin_in(client, admin_token, "Precedence Org")
    project_id, requirement_id = _requirement(client, org_admin, org["id"])
    _put(client, admin_token, org["id"], enabled=False, quota=1)
    client.put("/api/v1/system/file-uploads", json={"file_uploads_enabled": False}, headers=auth_headers(admin_token))
    try:
        refused = _upload(client, org_admin, project_id, requirement_id, b"xx")
        assert refused.status_code == 403 and refused.json()["detail"]["code"] == "uploads_disabled"
    finally:
        client.put("/api/v1/system/file-uploads", json={"file_uploads_enabled": True}, headers=auth_headers(admin_token))


# --- the limit ---------------------------------------------------------------------------------------------------


def test_a_file_at_the_limit_passes_and_one_byte_over_fails_with_the_figures(client, admin_token):
    org, org_admin = create_org_admin_in(client, admin_token, "Limit Org")
    project_id, requirement_id = _requirement(client, org_admin, org["id"])
    _put(client, admin_token, org["id"], quota=10)
    assert _upload(client, org_admin, project_id, requirement_id, b"0123456789").status_code == 201
    refused = _upload(client, org_admin, project_id, requirement_id, b"x")
    assert refused.status_code == 403
    detail = refused.json()["detail"]
    assert detail["code"] == "storage_quota_exceeded"
    assert detail["quota_bytes"] == 10 and detail["used_bytes"] == 10 and detail["remaining_bytes"] == 0
    assert "server administrator" in detail["message"]


def test_one_file_larger_than_the_space_left_fails_without_storing_anything(client, admin_token):
    org, org_admin = create_org_admin_in(client, admin_token, "Space Org")
    project_id, requirement_id = _requirement(client, org_admin, org["id"])
    _put(client, admin_token, org["id"], quota=10)
    assert _upload(client, org_admin, project_id, requirement_id, b"123456").status_code == 201
    assert _upload(client, org_admin, project_id, requirement_id, b"12345").status_code == 403
    assert _upload(client, org_admin, project_id, requirement_id, b"1234").status_code == 201


def test_deleting_a_file_frees_space_and_the_next_upload_passes(client, admin_token):
    org, org_admin = create_org_admin_in(client, admin_token, "Free Org")
    project_id, requirement_id = _requirement(client, org_admin, org["id"])
    _put(client, admin_token, org["id"], quota=4)
    stored = _upload(client, org_admin, project_id, requirement_id, b"abcd")
    assert _upload(client, org_admin, project_id, requirement_id, b"e").status_code == 403
    assert client.delete(
        f"/api/v1/projects/{project_id}/requirements/{requirement_id}/files/{stored.json()['id']}",
        headers=auth_headers(org_admin),
    ).status_code == 204
    assert _upload(client, org_admin, project_id, requirement_id, b"e").status_code == 201


def test_lowering_the_limit_below_usage_blocks_new_files_and_keeps_reading_and_deleting(client, admin_token):
    org, org_admin = create_org_admin_in(client, admin_token, "Lower Org")
    project_id, requirement_id = _requirement(client, org_admin, org["id"])
    stored = _upload(client, org_admin, project_id, requirement_id, b"abcdefgh")
    assert _put(client, admin_token, org["id"], quota=2).status_code == 200
    assert _upload(client, org_admin, project_id, requirement_id, b"x").status_code == 403
    file_id = stored.json()["id"]
    assert client.get(f"/api/v1/files/{file_id}", headers=auth_headers(org_admin)).content == b"abcdefgh"
    assert client.delete(
        f"/api/v1/projects/{project_id}/requirements/{requirement_id}/files/{file_id}", headers=auth_headers(org_admin),
    ).status_code == 204


def test_a_limit_never_affects_another_organisation(client, admin_token):
    first, first_admin = create_org_admin_in(client, admin_token, "Isolated One")
    second, second_admin = create_org_admin_in(client, admin_token, "Isolated Two")
    p1, r1 = _requirement(client, first_admin, first["id"])
    p2, r2 = _requirement(client, second_admin, second["id"])
    _put(client, admin_token, first["id"], quota=1)
    assert _upload(client, first_admin, p1, r1, b"xx").status_code == 403
    assert _upload(client, second_admin, p2, r2, b"x" * 5000).status_code == 201
    assert client.get(_storage(second["id"]), headers=auth_headers(second_admin)).json()["used_bytes"] == 5000
    assert client.get(_storage(first["id"]), headers=auth_headers(first_admin)).json()["used_bytes"] == 0


def test_stored_report_outputs_count_toward_usage_and_match_the_usage_table(client, admin_token):
    org, org_admin = create_org_admin_in(client, admin_token, "Outputs Org")
    project_id, requirement_id = _requirement(client, org_admin, org["id"])
    _upload(client, org_admin, project_id, requirement_id, b"x" * 100)
    with SessionLocal() as db:
        db.add(GeneratedReport(
            organization_id=uuid.UUID(org["id"]), scope="project", layout_id=uuid.uuid4(), layout_name="L", layout_version=1,
            tree_hash="h", format="pdf", engine_version="1", source_digest="d", output_key="k", output_filename="o.pdf",
            output_size=400,
        ))
        db.commit()
    assert client.get(_storage(org["id"]), headers=auth_headers(org_admin)).json()["used_bytes"] == 500
    stats = client.get(f"/api/v1/orgs/{org['id']}/overview-stats", headers=auth_headers(org_admin)).json()
    assert stats["total_file_size_bytes"] == 500
    _put(client, admin_token, org["id"], quota=550)
    assert _upload(client, org_admin, project_id, requirement_id, b"x" * 51).status_code == 403
    assert _upload(client, org_admin, project_id, requirement_id, b"x" * 50).status_code == 201


def test_the_server_default_applies_until_the_organisation_has_its_own_limit(client, admin_token):
    org, org_admin = create_org_admin_in(client, admin_token, "Default Limit Org")
    project_id, requirement_id = _requirement(client, org_admin, org["id"])
    try:
        set_default = client.put(
            "/api/v1/system/default-storage-quota", json={"default_storage_quota_bytes": 3}, headers=auth_headers(admin_token),
        )
        assert set_default.status_code == 200
        body = client.get(_storage(org["id"]), headers=auth_headers(org_admin)).json()
        assert body["effective_quota_bytes"] == 3 and body["quota_source"] == "server" and body["storage_quota_bytes"] is None
        assert _upload(client, org_admin, project_id, requirement_id, b"abcd").status_code == 403
        _put(client, admin_token, org["id"], quota=100)
        assert _upload(client, org_admin, project_id, requirement_id, b"abcd").status_code == 201
        assert client.get(_storage(org["id"]), headers=auth_headers(org_admin)).json()["quota_source"] == "organization"
    finally:
        client.put(
            "/api/v1/system/default-storage-quota", json={"default_storage_quota_bytes": None}, headers=auth_headers(admin_token),
        )


def test_only_a_server_administrator_sets_the_server_default_and_it_is_audited(client, admin_token):
    org, _ = create_org_admin_in(client, admin_token, "Default Owner Org")
    manager = _manager(client, admin_token, org["id"], "default-manager@example.com")
    body = {"default_storage_quota_bytes": 7}
    assert client.put("/api/v1/system/default-storage-quota", json=body, headers=auth_headers(manager)).status_code == 403
    assert client.get("/api/v1/system/default-storage-quota", headers=auth_headers(manager)).status_code == 403
    try:
        assert client.put("/api/v1/system/default-storage-quota", json=body, headers=auth_headers(admin_token)).status_code == 200
        with SessionLocal() as db:
            event = db.scalars(select(AuditEvent).where(AuditEvent.action == "default_storage_quota_updated")).one()
            assert event.detail == {"before": None, "after": 7}
    finally:
        client.put(
            "/api/v1/system/default-storage-quota", json={"default_storage_quota_bytes": None}, headers=auth_headers(admin_token),
        )


def test_concurrent_uploads_near_the_limit_cannot_both_pass(client, admin_token):
    """Two sessions each ask for 6 bytes with 10 left: the second waits for the first's row lock and then sees the space
    gone, so only one passes."""
    with SessionLocal() as db:
        org = Organization(name="Race Org", storage_quota_bytes=10)
        db.add(org)
        db.commit()
        org_id = org.id
        uploader = db.scalar(select(User.id))
    first, second = SessionLocal(), SessionLocal()
    result: dict[str, object] = {}
    try:
        assert storage_usage.refusal(first, org_id, 6) is None
        first.add(FileAsset(
            organization_id=org_id, storage_backend="local", storage_key="race/a", filename="a", content_type="x",
            size_bytes=6, uploaded_by=uploader,
        ))
        first.flush()

        def attempt() -> None:
            result["refusal"] = storage_usage.refusal(second, org_id, 6)

        worker = threading.Thread(target=attempt)
        worker.start()
        time.sleep(0.5)
        assert worker.is_alive(), "the second upload must wait for the first transaction"
        first.commit()
        worker.join(timeout=10)
        assert not worker.is_alive()
        refusal = result["refusal"]
        assert isinstance(refusal, dict) and refusal["code"] == "storage_quota_exceeded"
        assert refusal["used_bytes"] == 6
    finally:
        first.rollback()
        second.rollback()
        first.close()
        second.close()
        with SessionLocal() as db:
            db.query(FileAsset).filter(FileAsset.organization_id == org_id).delete()
            db.query(Organization).filter(Organization.id == org_id).delete()
            db.commit()


# --- the nearly full notice --------------------------------------------------------------------------------------


def test_the_nearly_full_notice_goes_to_administrators_once_per_crossing(client, admin_token):
    org, org_admin = create_org_admin_in(client, admin_token, "Notice Org")
    project_id, requirement_id = _requirement(client, org_admin, org["id"])
    _put(client, admin_token, org["id"], quota=100)
    assert _upload(client, org_admin, project_id, requirement_id, b"x" * 50).status_code == 201
    assert _notified(org["id"]) == 0
    crossing = _upload(client, org_admin, project_id, requirement_id, b"x" * 40)
    assert crossing.status_code == 201 and _notified(org["id"]) == 1
    assert _upload(client, org_admin, project_id, requirement_id, b"x" * 5).status_code == 201
    assert _notified(org["id"]) == 1, "no second notice while still above the level"
    stored = client.get(_storage(org["id"]), headers=auth_headers(org_admin)).json()
    assert stored["warning"] is True
    with SessionLocal() as db:
        event = db.scalars(
            select(AuditEvent).where(AuditEvent.action == "storage_limit_near", AuditEvent.entity_id == org["id"])
        ).one()
        assert set(event.detail) == {"used_bytes", "quota_bytes", "recipient_count"}


def test_the_notice_is_sent_again_after_usage_falls_and_crosses_again(client, admin_token):
    org, org_admin = create_org_admin_in(client, admin_token, "Renotice Org")
    project_id, requirement_id = _requirement(client, org_admin, org["id"])
    _put(client, admin_token, org["id"], quota=100)
    big = _upload(client, org_admin, project_id, requirement_id, b"x" * 95)
    assert _notified(org["id"]) == 1
    client.delete(
        f"/api/v1/projects/{project_id}/requirements/{requirement_id}/files/{big.json()['id']}", headers=auth_headers(org_admin),
    )
    assert _upload(client, org_admin, project_id, requirement_id, b"x" * 95).status_code == 201
    assert _notified(org["id"]) == 2


def test_the_overview_stats_carry_the_limit_and_the_switch(client, admin_token):
    org, org_admin = create_org_admin_in(client, admin_token, "Stats Org")
    _put(client, admin_token, org["id"], enabled=False, quota=1234)
    stats = client.get(f"/api/v1/orgs/{org['id']}/overview-stats", headers=auth_headers(org_admin)).json()
    assert stats["storage_quota_bytes"] == 1234 and stats["uploads_enabled"] is False and stats["storage_warning"] is False
    assert client.get(f"/api/v1/orgs/{org['id']}", headers=auth_headers(org_admin)).json()["file_uploads_enabled"] is False


# --- import ------------------------------------------------------------------------------------------------------


def _bundle_with_file(client, token, org_id) -> bytes:
    project_id, requirement_id = _requirement(client, token, org_id)
    assert _upload(client, token, project_id, requirement_id, b"hello world").status_code == 201
    return client.get(f"/api/v1/projects/{project_id}/export", headers=auth_headers(token)).content


def _import(client, token, org_id, bundle: bytes, name: str, **extra):
    return client.post(
        "/api/v1/projects/import", data={"organization_id": org_id, "name": name, **extra},
        files={"file": ("bundle.zip", bundle, "application/zip")}, headers=auth_headers(token),
    )


def test_an_import_that_does_not_fit_is_refused_with_the_figures_before_any_row_is_written(client, admin_token):
    org, org_admin = create_org_admin_in(client, admin_token, "Import Fit Org")
    bundle = _bundle_with_file(client, org_admin, org["id"])
    _put(client, admin_token, org["id"], quota=15)
    refused = _import(client, org_admin, org["id"], bundle, "Too big")
    assert refused.status_code == 403, refused.text
    detail = refused.json()["detail"]
    assert detail["code"] == "storage_quota_exceeded" and detail["file_count"] == 1
    assert detail["file_bytes"] == len(b"hello world") and detail["remaining_bytes"] == 4
    projects = client.get("/api/v1/projects", headers=auth_headers(org_admin)).json()
    assert "Too big" not in [p["name"] for p in projects]


def test_an_import_that_does_not_fit_goes_ahead_without_files_when_chosen(client, admin_token):
    org, org_admin = create_org_admin_in(client, admin_token, "Import Skip Org")
    bundle = _bundle_with_file(client, org_admin, org["id"])
    _put(client, admin_token, org["id"], quota=15)
    skipped = _import(client, org_admin, org["id"], bundle, "Without files", skip_files="true")
    assert skipped.status_code == 201, skipped.text
    assert any("storage space" in warning for warning in skipped.json().get("warnings", []))


def test_an_import_that_fits_brings_its_files(client, admin_token):
    org, org_admin = create_org_admin_in(client, admin_token, "Import Fits Org")
    bundle = _bundle_with_file(client, org_admin, org["id"])
    _put(client, admin_token, org["id"], quota=1000)
    assert _import(client, org_admin, org["id"], bundle, "Fits").status_code == 201
    with SessionLocal() as db:
        total = storage_usage.used_bytes(db, uuid.UUID(org["id"]))
    assert total == 2 * len(b"hello world")
