"""Tests for the post-restore checks (`services.dr_verify`) and `scripts/dr_verify.py`: each check passes on a
healthy platform and fails, naming what is wrong, when one thing is damaged, and no report carries row content.

Each test builds its own data; the checks run against the test application through its own client, the way the
restore-test runs them against a restored stack.
"""

from __future__ import annotations

import io
import json
import random
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import delete, select

from app.database import SessionLocal
from app.models.file import FileAsset
from app.models.organization import Organization
from app.models.requirement import Requirement
from app.models.user import User
from app.services import dr_verify
from app.services import email as email_service
from app.services.audit import log_event
from app.services.dr_restore import code_revisions
from app.services.dr_stats import EncryptedColumnProbe, collect_stats
from app.storage_backends import LocalFileStorageBackend
from tests.link_world import World

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
_PROJECT_WORD = "Distinctive"


@pytest.fixture
def world(client, admin_token) -> World:
    return World(client, admin_token, "Verify Org")


@pytest.fixture
def storage(tmp_path) -> LocalFileStorageBackend:
    return LocalFileStorageBackend(str(tmp_path))


@pytest.fixture
def delivery_disabled(monkeypatch):
    monkeypatch.setattr(email_service.settings, "email_delivery", "disabled")


def _stats(storage=None):
    with SessionLocal() as db:
        try:
            return collect_stats(db, storage)
        finally:
            db.rollback()


def _manifest(stats):
    """The verifier reads only the manifest's statistics."""
    return SimpleNamespace(stats=stats)


def _file(db, org_id, user_id, storage: LocalFileStorageBackend, data: bytes, *, store: bool = True, size: int | None = None) -> str:
    key = f"verify/{uuid.uuid4().hex}"
    if store:
        storage.save(key, data)
    db.add(
        FileAsset(
            organization_id=org_id,
            storage_backend=storage.name,
            storage_key=key,
            filename="f.txt",
            content_type="text/plain",
            size_bytes=len(data) if size is None else size,
            uploaded_by=user_id,
        )
    )
    db.flush()
    return key


def _run(client, manifest, storage, **kwargs):
    with SessionLocal() as db:
        return dr_verify.run_verification(
            manifest, db, storage, client, head_revisions=code_revisions()[1], key_supplied=True, rng=random.Random(1), **kwargs
        )


def _by_name(report) -> dict[str, dr_verify.Check]:
    return {check.name: check for check in report.checks}


# --- migrations ---------------------------------------------------------------------------------------


def test_migrations_pass_at_the_manifest_revision_and_the_image_head(client):
    stats = _stats()
    head = code_revisions()[1]
    assert dr_verify.check_migrations(stats, _manifest(stats), head).ok


def test_migrations_fail_when_the_revision_differs_from_the_manifest(client):
    stats = _stats()
    other = stats.model_copy(update={"alembic_revision": "0001"})
    check = dr_verify.check_migrations(stats, _manifest(other), code_revisions()[1])
    assert not check.ok and "set was taken at 0001" in check.detail


def test_migrations_fail_when_the_revision_is_not_the_image_head(client):
    stats = _stats()
    check = dr_verify.check_migrations(stats, _manifest(stats), {"some-other-head"})
    assert not check.ok and "would still run" in check.detail


# --- statistics ---------------------------------------------------------------------------------------


def test_statistics_pass_when_nothing_changed(world):
    world.requirement(world.project("Alpha"), "One")
    stats = _stats()
    assert dr_verify.check_statistics(_stats(), _manifest(stats)).ok


def test_statistics_name_a_deleted_row(world):
    project = world.project("Alpha")
    world.requirement(project, "One")
    world.requirement(project, "Two")
    expected = _stats()
    with SessionLocal() as db:
        db.execute(delete(Requirement).where(Requirement.id == db.scalar(select(Requirement.id).limit(1))))
        db.commit()
    check = dr_verify.check_statistics(_stats(), _manifest(expected))
    assert not check.ok
    paths = {m["path"] for m in check.data["mismatches"]}
    assert "tables.requirements" in paths and "business.records.requirement" in paths


def test_statistics_allow_exactly_the_rows_the_restore_wrote(world):
    world.requirement(world.project("Alpha"), "One")
    expected = _stats()
    with SessionLocal() as db:  # one audit event, as clearing unreadable secrets writes
        log_event(db, entity_type="restore", entity_id="set", action="secrets_cleared", actor_id=None, detail={"cleared": {}})
        db.commit()
    actual = _stats()
    assert not dr_verify.check_statistics(actual, _manifest(expected)).ok
    allowed = dr_verify.check_statistics(actual, _manifest(expected), {"audit_events": 1})
    assert allowed.ok and "1 audit rows the restore wrote" in allowed.detail
    assert not dr_verify.check_statistics(actual, _manifest(expected), {"audit_events": 2}).ok, "a different extra count must still fail"


# --- stored objects -----------------------------------------------------------------------------------


def test_file_objects_pass_when_every_object_reads_back_at_its_size(world, storage):
    with SessionLocal() as db:
        org = db.scalar(select(Organization).limit(1))
        user = db.scalar(select(User).limit(1))
        _file(db, org.id, user.id, storage, b"hello")
        _file(db, org.id, user.id, storage, b"world!!")
        db.commit()
    stats = _stats(storage)
    with SessionLocal() as db:
        check = dr_verify.check_file_objects(db, stats, storage, 10, random.Random(1))
    assert check.ok, check.detail
    assert "2 file records" in check.detail


def test_file_objects_fail_for_a_record_with_no_object(world, storage):
    with SessionLocal() as db:
        org, user = db.scalar(select(Organization).limit(1)), db.scalar(select(User).limit(1))
        _file(db, org.id, user.id, storage, b"x", store=False)
        db.commit()
    stats = _stats(storage)
    with SessionLocal() as db:
        check = dr_verify.check_file_objects(db, stats, storage, 10, random.Random(1))
    assert not check.ok and len(check.data["missing_file_ids"]) == 1


def test_file_objects_fail_for_an_object_of_the_wrong_size(world, storage):
    with SessionLocal() as db:
        org, user = db.scalar(select(Organization).limit(1)), db.scalar(select(User).limit(1))
        _file(db, org.id, user.id, storage, b"short", size=999)
        db.commit()
    stats = _stats(storage)
    with SessionLocal() as db:
        check = dr_verify.check_file_objects(db, stats, storage, 10, random.Random(1))
    assert not check.ok and "differ in size" in check.detail


def test_file_objects_fail_when_the_probe_was_skipped(client, storage):
    with SessionLocal() as db:
        check = dr_verify.check_file_objects(db, _stats(None), storage, 10, random.Random(1))
    assert not check.ok


# --- encrypted columns --------------------------------------------------------------------------------


def _with_encrypted(stats, **columns):
    """A copy of `stats` whose encrypted-column probes are exactly `columns`."""
    copy = stats.model_copy(deep=True)
    copy.probes.encrypted_columns = dict(columns)
    return copy


def test_encrypted_columns_pass_when_every_value_decrypts(client):
    stats = _with_encrypted(_stats(), **{"users.totp_secret": EncryptedColumnProbe(rows=3, undecryptable=0)})
    check = dr_verify.check_encrypted_columns(stats, key_supplied=True, allow_unreadable=False)
    assert check.ok and "3 encrypted values" in check.detail


def test_encrypted_columns_name_what_the_key_cannot_read(client):
    stats = _with_encrypted(_stats(), **{"users.totp_secret": EncryptedColumnProbe(rows=3, undecryptable=2)})
    check = dr_verify.check_encrypted_columns(stats, key_supplied=True, allow_unreadable=False)
    assert not check.ok and check.data["undecryptable"] == {"users.totp_secret": 2}


def test_encrypted_columns_cannot_be_judged_without_a_key(client):
    check = dr_verify.check_encrypted_columns(_stats(), key_supplied=False, allow_unreadable=False)
    assert not check.ok and "not set" in check.detail


# --- email --------------------------------------------------------------------------------------------


def test_email_check_passes_when_delivery_is_disabled(delivery_disabled):
    assert dr_verify.check_email_disabled().ok


def test_email_check_fails_when_a_send_would_go_out(monkeypatch):
    sent = []

    async def fake_send(*args, **kwargs):
        sent.append(args)

    monkeypatch.setattr(email_service.settings, "email_delivery", "smtp")
    monkeypatch.setattr(email_service.aiosmtplib, "send", fake_send)
    check = dr_verify.check_email_disabled()
    assert not check.ok and sent, "the send attempt must have reached the (fake) SMTP client"


# --- API ----------------------------------------------------------------------------------------------


def test_api_smoke_passes_for_a_project_manager_with_a_record(world, client):
    project = world.project("Alpha")
    world.requirement(project, f"{_PROJECT_WORD} requirement")
    with SessionLocal() as db:
        check = dr_verify.check_api(db, client)
    assert check.ok, check.detail
    assert check.data["steps"] == 7


def test_api_smoke_skips_the_record_steps_on_an_empty_platform(client):
    with SessionLocal() as db:
        check = dr_verify.check_api(db, client)
    assert check.ok and check.data == {"skipped": True}


def test_api_smoke_fails_when_a_step_is_refused(world, client, monkeypatch):
    world.requirement(world.project("Alpha"), f"{_PROJECT_WORD} requirement")
    real_create = dr_verify.create_access_token  # a token from another credential epoch must be refused
    monkeypatch.setattr(dr_verify, "create_access_token", lambda subject, token_version=0: real_create(subject, token_version=token_version + 1))
    with SessionLocal() as db:
        check = dr_verify.check_api(db, client)
    assert not check.ok and "identity answered 401" in check.detail


def test_login_check_accepts_a_good_password_and_refuses_a_bad_one(client):
    good = dr_verify.LoginCredentials("admin@example.com", "ChangeMe123!")
    assert dr_verify.check_login(client, good).ok
    bad = dr_verify.LoginCredentials("admin@example.com", "not-the-password")
    check = dr_verify.check_login(client, bad)
    assert not check.ok and "401" in check.detail and "not-the-password" not in check.detail


# --- credential recovery ------------------------------------------------------------------------------


def _force_reset_everyone() -> None:
    from app.services import credential_reset

    with SessionLocal() as db:
        scope = credential_reset.ResetScope("all")
        credential_reset.force_reset(
            db, credential_reset.resolve_scope(db, scope), scope=scope, reset_2fa=False, actor_id=None, actor_label="cli:test"
        )
        db.commit()


def test_credential_recovery_lets_a_locked_out_administrator_back_in_once(client):
    _force_reset_everyone()
    with SessionLocal() as db:
        check = dr_verify.check_credential_recovery(db, client)
    assert check.ok, check.detail
    assert check.data["local_accounts"] == 1 and "server administrator" in check.detail
    with SessionLocal() as db:
        assert db.query(User).filter(User.email == "admin@example.com").one().must_reset_credentials is False


def test_credential_recovery_fails_when_an_account_was_not_marked(client):
    _force_reset_everyone()
    with SessionLocal() as db:
        db.query(User).filter(User.email == "admin@example.com").update({"must_reset_credentials": False})
        db.commit()
        check = dr_verify.check_credential_recovery(db, client)
    assert not check.ok and "not marked" in check.detail


def test_credential_recovery_fails_when_a_pre_reset_session_still_works(client, monkeypatch):
    _force_reset_everyone()
    real = dr_verify.create_access_token  # a "stale" token that carries the current epoch is accepted: the check must notice
    monkeypatch.setattr(dr_verify, "create_access_token", lambda subject, token_version=0: real(subject, token_version=token_version + 1))
    with SessionLocal() as db:
        check = dr_verify.check_credential_recovery(db, client)
    assert not check.ok and "still accepted" in check.detail


def test_credential_recovery_with_no_local_accounts_is_a_stated_skip(client):
    with SessionLocal() as db:
        db.query(User).update({"password_hash": None})
        db.commit()
        check = dr_verify.check_credential_recovery(db, client)
    assert check.ok and check.data == {"skipped": True}


def test_credential_recovery_reports_neither_the_link_nor_the_password(client):
    _force_reset_everyone()
    with SessionLocal() as db:
        check = dr_verify.check_credential_recovery(db, client)
    text = json.dumps(check.__dict__, default=str)
    assert "reset-password" not in text and "#token" not in text


# --- the whole run ------------------------------------------------------------------------------------


def test_a_healthy_platform_passes_every_check(world, client, storage, delivery_disabled):
    project = world.project("Alpha")
    world.requirement(project, f"{_PROJECT_WORD} requirement")
    manifest = _manifest(_stats(storage))
    report = _run(client, manifest, storage, login=dr_verify.LoginCredentials("admin@example.com", "ChangeMe123!"))
    assert report.result == "ok", [c.detail for c in report.checks if not c.ok]
    assert [c.name for c in report.checks] == [
        "migrations",
        "statistics",
        "file-objects",
        "encrypted-columns",
        "email-disabled",
        "api-smoke",
        "login",
    ]


def test_a_deleted_row_fails_the_run_and_the_report_holds_no_row_content(world, client, storage, delivery_disabled):
    project = world.project("Alpha")
    world.requirement(project, f"{_PROJECT_WORD} requirement")
    world.requirement(project, f"{_PROJECT_WORD} second")
    manifest = _manifest(_stats(storage))
    with SessionLocal() as db:
        db.execute(delete(Requirement).where(Requirement.id == db.scalar(select(Requirement.id).order_by(Requirement.created_at.desc()).limit(1))))
        db.commit()
    report = _run(client, manifest, storage)
    checks = _by_name(report)
    assert report.result == "failed"
    assert not checks["statistics"].ok
    text = json.dumps(report.to_json_dict())
    assert _PROJECT_WORD not in text and "Verify Org" not in text


def test_a_missing_object_fails_the_run(world, client, storage, delivery_disabled):
    world.requirement(world.project("Alpha"), f"{_PROJECT_WORD} requirement")
    with SessionLocal() as db:
        org, user = db.scalar(select(Organization).limit(1)), db.scalar(select(User).limit(1))
        key = _file(db, org.id, user.id, storage, b"payload")
        db.commit()
    manifest = _manifest(_stats(storage))
    storage.delete(key)
    report = _run(client, manifest, storage)
    assert report.result == "failed" and not _by_name(report)["file-objects"].ok


def test_a_check_that_raises_is_reported_by_class_name_only():
    def explode() -> dr_verify.Check:
        raise RuntimeError("secret row content")

    check = dr_verify._check("statistics", explode)
    assert not check.ok and "RuntimeError" in check.detail and "secret" not in check.detail


def test_an_unreadable_database_is_reported_not_raised(client, storage, delivery_disabled):
    class Broken:
        def rollback(self):
            pass

        def execute(self, *args, **kwargs):
            raise RuntimeError("password=hunter2")

    report = dr_verify.run_verification(_manifest(_stats(storage)), Broken(), storage, client, head_revisions=set(), key_supplied=True)
    assert report.result == "failed"
    assert "hunter2" not in json.dumps(report.to_json_dict())


# --- CLI ----------------------------------------------------------------------------------------------


def test_cli_rejects_an_unreadable_request(monkeypatch, capsys):
    sys.path.insert(0, str(_SCRIPTS))
    try:
        import dr_verify as cli
    finally:
        sys.path.pop(0)
    monkeypatch.setattr(sys, "stdin", io.StringIO("not json"))
    assert cli.main([]) == 2
    assert "cannot read the request" in capsys.readouterr().err
