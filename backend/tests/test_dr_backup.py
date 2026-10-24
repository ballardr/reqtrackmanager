"""Tests for the disaster-recovery backup tool: the restic wrapper's redaction, the incremental object
mirror, and `run_backup` end to end (real database snapshot, real restic and age, a fake object store and a
fake `pg_dump` unless a test needs the real one).

Tests that need the `restic`, `age` or `pg_dump` binaries skip when they are absent; CI installs them. Each
test works in its own temporary directories and, for the database, only reads, so none depends on state left
by another test or run.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tarfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from botocore.exceptions import ClientError

from app.config import get_settings
from app.database import engine
from app.services import dr_backup
from app.services.dr_backup import (
    AlreadyRunning,
    BackupConfig,
    BackupDeps,
    BackupError,
    archive_local_files,
    dump_database,
    run_backup,
    run_lock,
    write_bundle,
)
from app.services.dr_manifest import ComponentKind, SecretsMode, load_manifest
from app.services.dr_object_mirror import MirrorError, ObjectMirror, key_label
from app.services.dr_restic import Redactor, Restic, ResticError

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"

# CI sets REQUIRE_DR_TOOLS=1 in the backup image so a missing binary fails a test instead of skipping it.
_TOOLS_REQUIRED = os.environ.get("REQUIRE_DR_TOOLS") == "1"
needs_restic = pytest.mark.skipif(shutil.which("restic") is None and not _TOOLS_REQUIRED, reason="restic is not installed")
needs_age = pytest.mark.skipif(
    (shutil.which("age") is None or shutil.which("age-keygen") is None) and not _TOOLS_REQUIRED, reason="age is not installed"
)


def _pg_dump_16() -> str | None:
    """Finds a `pg_dump` of at least major version 16, or None."""
    candidates = [
        os.environ.get("BACKUP_PG_DUMP"),
        shutil.which("pg_dump"),
        "/usr/lib/postgresql/16/bin/pg_dump",
        "/usr/local/opt/postgresql@16/bin/pg_dump",
        "/opt/homebrew/opt/postgresql@16/bin/pg_dump",
    ]
    for path in candidates:
        if path and Path(path).exists():
            out = subprocess.run([path, "--version"], capture_output=True, text=True, check=False).stdout
            found = re.search(r"\) (\d+)", out)
            if found and int(found.group(1)) >= 16:
                return path
    return None


# --- fakes -----------------------------------------------------------------------------------------


class FakeBody:
    """The streaming body of a fake object."""

    def __init__(self, data: bytes) -> None:
        self._data = data

    def iter_chunks(self, size: int):
        for start in range(0, len(self._data), size):
            yield self._data[start : start + size]


class FakeS3:
    """The slice of a boto3 S3 client the mirror uses: a paginated listing and streaming gets."""

    def __init__(self, objects: dict[str, bytes] | None = None, page_size: int = 1000) -> None:
        self.objects = dict(objects or {})
        self.page_size = page_size
        self.fail_listing = False
        self.etag_override: dict[str, str] = {}
        self.gets: list[str] = []

    def get_paginator(self, name: str) -> FakeS3:
        assert name == "list_objects_v2"
        return self

    def paginate(self, Bucket: str):
        if self.fail_listing:
            raise ClientError({"Error": {"Code": "AccessDenied", "Message": "denied"}}, "ListObjectsV2")
        keys = sorted(self.objects)
        for start in range(0, max(len(keys), 1), self.page_size):
            yield {
                "Contents": [
                    {"Key": k, "Size": len(self.objects[k]), "ETag": f'"{self.etag_override.get(k, hashlib.md5(self.objects[k]).hexdigest())}"'}
                    for k in keys[start : start + self.page_size]
                ]
            }

    def get_object(self, Bucket: str, Key: str) -> dict[str, Any]:
        self.gets.append(Key)
        return {"Body": FakeBody(self.objects[Key])}


def _fake_dump(config: BackupConfig, db_url: str, snapshot_id: str, out: Path, redact: Redactor) -> None:
    """Stands in for `pg_dump`: records the snapshot id it was given."""
    out.write_bytes(b"PGDMP-fake " + snapshot_id.encode())


def _config(tmp_path: Path, **overrides: Any) -> BackupConfig:
    password = tmp_path / "password"
    password.write_text("correct horse battery staple")
    values: dict[str, Any] = {
        "staging_dir": tmp_path / "staging",
        "repository": str(tmp_path / "repo"),
        "password_file": password,
        "status_dir": tmp_path / "status",
        "secrets_mode": SecretsMode.NONE,
        "check_subset": "100%",
    }
    values.update(overrides)
    return BackupConfig(**values)


def _deps(config: BackupConfig, s3: FakeS3 | None = None, *, backend: str = "s3", **overrides: Any) -> BackupDeps:
    fixed = datetime(2026, 10, 24, 2, 0, 0, tzinfo=UTC)
    counter = {"n": 0}

    def now() -> datetime:
        counter["n"] += 1
        return fixed + timedelta(seconds=counter["n"])

    values: dict[str, Any] = {
        "engine": engine,
        "db_url": get_settings().database_url,
        "storage_backend": backend,
        "restic": Restic(config.password_file, redactor=Redactor(["hunter2-secret"]), probe_timeout=5),
        "storage_client": s3,
        "storage_bucket": "bucket",
        "dumper": _fake_dump,
        "now": now,
    }
    values.update(overrides)
    return BackupDeps(**values)


def _restore_latest(config: BackupConfig, tmp_path: Path) -> Path:
    target = tmp_path / "restored"
    Restic(config.password_file).restore(config.repository, "latest", target)
    return target


def _set_dir(restored: Path) -> Path:
    found = list(restored.rglob("manifest.json"))
    assert len(found) == 1
    return found[0].parent


# --- redaction ---------------------------------------------------------------------------------------


def test_redactor_masks_url_credentials_and_secrets():
    redact = Redactor(["topsecretvalue"])
    text = "failed sftp://backup:pa55w0rd@host/path and rest:https://u:p@x.example/repo with topsecretvalue inside"
    out = redact(text)
    assert "pa55w0rd" not in out and "topsecretvalue" not in out and "u:p@" not in out
    assert "sftp://***@host/path" in out


def test_redactor_ignores_empty_and_tiny_secrets():
    assert Redactor(["", "ab"])("abc") == "abc"


@needs_restic
def test_restic_errors_are_redacted(tmp_path: Path):
    password = tmp_path / "pw"
    password.write_text("x")
    restic = Restic(password, redactor=Redactor(["leakme-123"]))
    with pytest.raises(ResticError) as caught:
        restic.run("sftp://user:leakme-123@127.0.0.1:1/none", "snapshots")
    assert "leakme-123" not in str(caught.value)


def test_secret_values_masks_secret_named_env_entries_only(tmp_path: Path):
    env_file = tmp_path / "env"
    lines = ["# JWT_SECRET=commented-out-value", "JWT_SECRET=jwt-value-123", "SMTP_PASSWORD=smtp-pass-456"]
    lines += ["BACKUP_DESTINATIONS=/mnt/nfs/offsite", "SMTP_HOST=mail.example.com"]
    env_file.write_text("\n".join(lines) + "\n")
    redact = Redactor(dr_backup.secret_values(env_file))
    out = redact("jwt-value-123 smtp-pass-456 /mnt/nfs/offsite mail.example.com commented-out-value")
    assert out == "*** *** /mnt/nfs/offsite mail.example.com commented-out-value"


# --- object mirror -----------------------------------------------------------------------------------


def _mirror(tmp_path: Path, s3: FakeS3) -> ObjectMirror:
    return ObjectMirror(s3, "bucket", tmp_path / "objects", tmp_path / "state.json")


def test_mirror_downloads_everything_across_pages(tmp_path: Path):
    s3 = FakeS3({f"org/{i:04d}/file": f"data-{i}".encode() for i in range(1105)}, page_size=1000)
    result = _mirror(tmp_path, s3).sync()
    assert result.count == 1105 and result.downloaded == 1105
    assert (tmp_path / "objects/org/1104/file").read_bytes() == b"data-1104"
    assert result.bytes == sum(len(v) for v in s3.objects.values())


def test_mirror_second_sync_fetches_only_changes(tmp_path: Path):
    s3 = FakeS3({"a/1": b"one", "a/2": b"two"})
    mirror = _mirror(tmp_path, s3)
    first = mirror.sync()
    s3.gets.clear()
    s3.objects["a/3"] = b"three"
    s3.objects["a/2"] = b"TWO!"  # overwritten under the same key: size and ETag both change
    second = mirror.sync()
    assert sorted(s3.gets) == ["a/2", "a/3"]
    assert second.downloaded == 2 and second.digest != first.digest
    assert (tmp_path / "objects/a/2").read_bytes() == b"TWO!"


def test_mirror_redownloads_a_file_damaged_locally(tmp_path: Path):
    s3 = FakeS3({"k": b"payload"})
    mirror = _mirror(tmp_path, s3)
    mirror.sync()
    (tmp_path / "objects/k").write_bytes(b"x")
    s3.gets.clear()
    mirror.sync()
    assert s3.gets == ["k"] and (tmp_path / "objects/k").read_bytes() == b"payload"


def test_mirror_keeps_a_deleted_object_for_one_more_run_then_drops_it(tmp_path: Path):
    s3 = FakeS3({"keep": b"k", "gone": b"g"})
    mirror = _mirror(tmp_path, s3)
    mirror.sync()
    del s3.objects["gone"]
    second = mirror.sync()
    assert second.flagged_missing == 1 and second.count == 1
    assert (tmp_path / "objects/gone").exists(), "the set taken this run may still reference it"
    third = mirror.sync()
    assert third.removed == 1 and not (tmp_path / "objects/gone").exists()
    assert (tmp_path / "objects/keep").exists()


def test_mirror_listing_failure_flags_nothing_and_deletes_nothing(tmp_path: Path):
    s3 = FakeS3({"a": b"1"})
    mirror = _mirror(tmp_path, s3)
    mirror.sync()
    s3.fail_listing = True
    with pytest.raises(MirrorError):
        mirror.sync()
    s3.fail_listing = False
    again = mirror.sync()
    assert again.flagged_missing == 0 and again.downloaded == 0 and (tmp_path / "objects/a").exists()


@pytest.mark.parametrize("key", ["../escape", "/abs", "a//b", "dir/", "a/./b", "a/../../b"])
def test_mirror_refuses_unsafe_keys_without_naming_them(tmp_path: Path, key: str):
    s3 = FakeS3({key: b"x"})
    with pytest.raises(MirrorError) as caught:
        _mirror(tmp_path, s3).sync()
    assert key not in str(caught.value) and key_label(key) in str(caught.value)
    assert not (tmp_path.parent / "escape").exists()


def test_mirror_detects_corruption_against_an_md5_etag(tmp_path: Path):
    s3 = FakeS3({"k": b"payload"})
    s3.etag_override["k"] = hashlib.md5(b"something else").hexdigest()
    with pytest.raises(MirrorError, match="MD5"):
        _mirror(tmp_path, s3).sync()
    assert not (tmp_path / "objects/k").exists()


def test_mirror_does_not_md5_check_multipart_etags(tmp_path: Path):
    s3 = FakeS3({"k": b"payload"})
    s3.etag_override["k"] = "d41d8cd98f00b204e9800998ecf8427e-3"
    assert _mirror(tmp_path, s3).sync().count == 1


def test_mirror_digest_is_stable_and_content_sensitive(tmp_path: Path):
    s3 = FakeS3({"a": b"1", "b": b"2"})
    digest = _mirror(tmp_path, s3).sync().digest
    expected = hashlib.sha256()
    for key in ("a", "b"):
        expected.update(f"{key}\t1\t{hashlib.sha256(s3.objects[key]).hexdigest()}\n".encode())
    assert digest == expected.hexdigest()


# --- run_backup: success -----------------------------------------------------------------------------


@needs_restic
def test_run_stores_a_verifiable_set(tmp_path: Path):
    s3 = FakeS3({"org/a/file1": b"first file", "org/b/file2": b"second file"})
    config = _config(tmp_path)
    report = run_backup(config, _deps(config, s3))
    assert report.result == "ok", report.error

    restored = _restore_latest(config, tmp_path)
    set_dir = _set_dir(restored)
    manifest = load_manifest((set_dir / "manifest.json").read_text())
    assert manifest.set_id == report.set_id and manifest.secrets_mode is SecretsMode.NONE
    assert manifest.storage_backend == "s3" and manifest.alembic_revision
    assert manifest.objects and manifest.objects.count == 2 and manifest.objects.bytes == len(b"first file") + len(b"second file")
    assert set(manifest.components) == {ComponentKind.DATABASE, ComponentKind.OBJECTS}

    dump = set_dir / "database" / "reqtrack.dump"
    assert hashlib.sha256(dump.read_bytes()).hexdigest() == manifest.components[ComponentKind.DATABASE].sha256
    assert dump.read_bytes().startswith(b"PGDMP-fake 0")  # the id of a real exported snapshot
    mirror_copies = list(restored.rglob("file1"))
    assert len(mirror_copies) == 1 and mirror_copies[0].read_bytes() == b"first file"

    snapshots = Restic(config.password_file).snapshots(config.repository)
    assert len(snapshots) == 1 and f"set:{report.set_id}" in snapshots[0]["tags"]


@needs_restic
def test_run_leaves_no_staged_set_behind_and_writes_status_and_metrics(tmp_path: Path):
    config = _config(tmp_path)
    report = run_backup(config, _deps(config, FakeS3({"k": b"v"})))
    assert report.result == "ok"
    assert not (config.staging_dir / "sets" / report.set_id).exists()
    status = json.loads((config.status_dir / "status.json").read_text())
    assert status["result"] == "ok" and status["failed_step"] is None and status["last_success_timestamp"]
    prom = (config.status_dir / "reqtrack-backup.prom").read_text()
    assert "reqtrack_backup_last_run_success 1" in prom
    assert "reqtrack_backup_last_success_timestamp_seconds " in prom and "reqtrack_backup_set_bytes " in prom


@needs_restic
def test_run_with_local_backend_archives_the_file_store(tmp_path: Path):
    store = tmp_path / "local_files"
    (store / "org1").mkdir(parents=True)
    (store / "org1" / "doc.txt").write_text("local bytes")
    config = _config(tmp_path, local_files_dir=store)
    report = run_backup(config, _deps(config, backend="local"))
    assert report.result == "ok", report.error
    set_dir = _set_dir(_restore_latest(config, tmp_path))
    manifest = load_manifest((set_dir / "manifest.json").read_text())
    assert manifest.objects is None and ComponentKind.LOCAL_FILES in manifest.components
    with tarfile.open(set_dir / "local_files.tar") as archive:
        assert archive.extractfile("files/org1/doc.txt").read() == b"local bytes"  # type: ignore[union-attr]
    assert not (config.staging_dir / "objects").exists()


def test_missing_local_file_store_is_a_clear_failure(tmp_path: Path):
    with pytest.raises(BackupError, match="not mounted"):
        archive_local_files(tmp_path / "nope", tmp_path / "out.tar")


# --- run_backup: secrets -----------------------------------------------------------------------------


def _all_bytes(root: Path) -> bytes:
    return b"".join(p.read_bytes() for p in root.rglob("*") if p.is_file())


@needs_restic
def test_none_mode_stores_no_env_content_anywhere(tmp_path: Path):
    env_file = tmp_path / "env"
    env_file.write_text("APP_SECRET_ENCRYPTION_KEY=sentinel-key-value-91\nJWT_SECRET=sentinel-jwt-91\n")
    config = _config(tmp_path, secrets_mode=SecretsMode.NONE, env_file=env_file)
    report = run_backup(config, _deps(config, FakeS3({"k": b"v"})))
    assert report.result == "ok", report.error
    restored = _restore_latest(config, tmp_path)
    manifest = load_manifest((_set_dir(restored) / "manifest.json").read_text())
    assert manifest.secrets_mode is SecretsMode.NONE and ComponentKind.CONFIG not in manifest.components
    assert not list(restored.rglob("env.age"))
    for root in (restored, config.staging_dir, config.status_dir):
        assert b"sentinel-key-value-91" not in _all_bytes(root) and b"sentinel-jwt-91" not in _all_bytes(root)


@needs_restic
@needs_age
def test_config_mode_stores_the_env_encrypted_to_the_recipient(tmp_path: Path):
    identity = tmp_path / "identity.txt"
    keygen = subprocess.run(["age-keygen", "-o", str(identity)], capture_output=True, text=True, check=True)
    recipient = (keygen.stderr + keygen.stdout).split("Public key:")[1].split()[0]
    env_file = tmp_path / "env"
    env_file.write_text("APP_SECRET_ENCRYPTION_KEY=sentinel-key-value-92\n")
    config = _config(tmp_path, secrets_mode=SecretsMode.CONFIG, env_file=env_file, config_age_recipient=recipient)

    report = run_backup(config, _deps(config, FakeS3({"k": b"v"})))
    assert report.result == "ok", report.error
    set_dir = _set_dir(_restore_latest(config, tmp_path))
    manifest = load_manifest((set_dir / "manifest.json").read_text())
    entry = manifest.components[ComponentKind.CONFIG]
    ciphertext = (set_dir / entry.path).read_bytes()
    assert hashlib.sha256(ciphertext).hexdigest() == entry.sha256
    assert b"sentinel-key-value-92" not in ciphertext
    plain = subprocess.run(["age", "-d", "-i", str(identity), str(set_dir / entry.path)], capture_output=True, check=True).stdout
    assert plain == env_file.read_bytes()
    assert b"sentinel-key-value-92" not in _all_bytes(config.status_dir)


@pytest.mark.parametrize(
    ("recipient", "write_env"),
    [("", True), ("age1qqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqq", False)],
    ids=["no-recipient", "no-env-file"],
)
def test_config_mode_refuses_to_run_without_what_it_needs(tmp_path: Path, recipient: str, write_env: bool):
    env_file = tmp_path / "env"
    if write_env:
        env_file.write_text("A=b\n")
    config = _config(tmp_path, secrets_mode=SecretsMode.CONFIG, env_file=env_file, config_age_recipient=recipient)
    report = run_backup(config, _deps(config, FakeS3()))
    assert report.result == "failed" and report.step == "config"
    assert not Path(config.repository).exists(), "nothing may be stored by a run that cannot honour its mode"


# --- run_backup: failures ----------------------------------------------------------------------------


@pytest.mark.parametrize("content", [None, ""], ids=["missing", "empty"])
def test_missing_or_empty_repository_password_refuses_to_run(tmp_path: Path, content: str | None):
    config = _config(tmp_path)
    if content is None:
        config.password_file.unlink()
    else:
        config.password_file.write_text(content)
    report = run_backup(config, _deps(config, FakeS3({"k": b"v"})))
    assert report.result == "failed" and report.step == "config" and "password" in (report.error or "")
    assert not Path(config.repository).exists()


def test_dump_failure_fails_the_run_redacted_and_cleans_up(tmp_path: Path):
    fake_pg_dump = tmp_path / "pg_dump"
    fake_pg_dump.write_text('#!/bin/sh\necho "connection to server failed, password $PGPASSWORD rejected" >&2\nexit 1\n')
    fake_pg_dump.chmod(fake_pg_dump.stat().st_mode | stat.S_IXUSR)
    config = _config(tmp_path, pg_dump=str(fake_pg_dump))
    deps = _deps(config, FakeS3(), db_url="postgresql://reqtrack:hunter2-secret@localhost:5432/reqtrack", dumper=dump_database)
    report = run_backup(config, deps)
    assert report.result == "failed" and report.step == "dump"
    assert "hunter2-secret" not in (report.error or "")
    status_text = (config.status_dir / "status.json").read_text()
    assert "hunter2-secret" not in status_text and '"failed_step": "dump"' in status_text
    assert not (config.staging_dir / "sets" / report.set_id).exists()


@needs_restic
def test_a_failed_run_keeps_the_previous_success_time(tmp_path: Path):
    config = _config(tmp_path)
    first = run_backup(config, _deps(config, FakeS3({"k": b"v"})))
    assert first.result == "ok"
    before = json.loads((config.status_dir / "status.json").read_text())["last_success_timestamp"]

    def broken(*args: Any) -> None:
        raise BackupError("dump", "pg_dump failed (exit 1): boom")

    second = run_backup(config, _deps(config, FakeS3(), dumper=broken))
    assert second.result == "failed"
    status = json.loads((config.status_dir / "status.json").read_text())
    assert status["result"] == "failed" and status["last_success_timestamp"] == before
    prom = (config.status_dir / "reqtrack-backup.prom").read_text()
    assert "reqtrack_backup_last_run_success 0" in prom and f"reqtrack_backup_last_success_timestamp_seconds {before:.0f}" in prom


def test_storage_down_fails_the_run_before_anything_is_stored(tmp_path: Path):
    s3 = FakeS3({"k": b"v"})
    s3.fail_listing = True
    config = _config(tmp_path)
    report = run_backup(config, _deps(config, s3))
    assert report.result == "failed" and report.step == "mirror"
    assert not Path(config.repository).exists()
    assert not (config.staging_dir / "sets" / report.set_id).exists()


def test_unexpected_exception_is_recorded_by_class_only(tmp_path: Path):
    def explode(*args: Any) -> None:
        raise ValueError("row value: alice@example.com")

    config = _config(tmp_path)
    report = run_backup(config, _deps(config, FakeS3(), dumper=explode))
    assert report.result == "failed" and report.error == "unexpected ValueError"


def test_concurrent_run_is_refused_and_does_not_touch_status(tmp_path: Path):
    config = _config(tmp_path)
    with run_lock(config.staging_dir), pytest.raises(AlreadyRunning):
        run_backup(config, _deps(config, FakeS3()))
    assert not (config.status_dir / "status.json").exists()
    with run_lock(config.staging_dir):  # released after the refused run
        pass


def test_run_restores_the_process_umask(tmp_path: Path):
    config = _config(tmp_path)
    before = os.umask(0o022)
    try:
        run_backup(config, _deps(config, FakeS3(), dumper=lambda *a: (_ for _ in ()).throw(BackupError("dump", "x"))))
        assert os.umask(0o022) == 0o022
    finally:
        os.umask(before)


# --- run_backup: destinations and retention ------------------------------------------------------------


@needs_restic
def test_snapshot_is_copied_to_each_destination(tmp_path: Path):
    config = _config(tmp_path, destinations_raw=f"{tmp_path / 'dest1'}, {tmp_path / 'dest2'}")
    report = run_backup(config, _deps(config, FakeS3({"k": b"v"})))
    assert report.result == "ok", report.error
    assert [d.ok for d in report.destinations] == [True, True]
    restic = Restic(config.password_file)
    primary = restic.snapshots(config.repository)
    for name in ("dest1", "dest2"):
        copied = restic.snapshots(str(tmp_path / name))
        assert [s["tags"] for s in copied] == [s["tags"] for s in primary]


@needs_restic
def test_a_failed_destination_fails_the_run_but_keeps_the_primary_snapshot(tmp_path: Path):
    config = _config(tmp_path, destinations_raw=f"{tmp_path / 'good'},/dev/null/unusable")
    report = run_backup(config, _deps(config, FakeS3({"k": b"v"})))
    assert report.result == "failed" and report.snapshot_id
    assert [d.ok for d in report.destinations] == [True, False]
    assert len(Restic(config.password_file).snapshots(config.repository)) == 1
    status = json.loads((config.status_dir / "status.json").read_text())
    assert status["destinations"][1]["ok"] is False
    assert 'reqtrack_backup_destination_up{destination="2"} 0' in (config.status_dir / "reqtrack-backup.prom").read_text()


@needs_restic
def test_retention_prunes_to_the_policy(tmp_path: Path):
    config = _config(tmp_path, keep_daily=1, keep_weekly=0, keep_monthly=0)
    for _ in range(3):
        assert run_backup(config, _deps(config, FakeS3({"k": b"v"}))).result == "ok"
    assert len(Restic(config.password_file).snapshots(config.repository)) == 1


@needs_restic
def test_repeated_runs_store_unchanged_objects_once(tmp_path: Path):
    config = _config(tmp_path, keep_daily=7)
    s3 = FakeS3({"big": os.urandom(300_000)})
    first = run_backup(config, _deps(config, s3))
    second = run_backup(config, _deps(config, s3))
    assert first.bytes_added > 300_000 * 0.9
    assert second.bytes_added < first.bytes_added * 0.2, "unchanged objects must be deduplicated"


@needs_restic
def test_wrong_repository_password_is_not_mistaken_for_a_new_repository(tmp_path: Path):
    config = _config(tmp_path)
    assert run_backup(config, _deps(config, FakeS3({"k": b"v"}))).result == "ok"
    config.password_file.write_text("a different password")
    report = run_backup(config, _deps(config, FakeS3({"k": b"v"})))
    assert report.result == "failed" and "password" in (report.error or "")


@needs_restic
def test_a_hung_restic_command_times_out_instead_of_holding_the_lock(tmp_path: Path):
    password = tmp_path / "pw"
    password.write_text("x")
    fake = tmp_path / "restic"
    fake.write_text("#!/bin/sh\nsleep 30\n")
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    with pytest.raises(ResticError, match="timed out"):
        Restic(password, binary=str(fake), timeout=0.5).run("repo", "snapshots")


# --- bundle --------------------------------------------------------------------------------------------


@needs_restic
@needs_age
def test_bundle_is_an_age_encrypted_tar_of_the_latest_set(tmp_path: Path):
    identity = tmp_path / "identity.txt"
    keygen = subprocess.run(["age-keygen", "-o", str(identity)], capture_output=True, text=True, check=True)
    recipient = (keygen.stderr + keygen.stdout).split("Public key:")[1].split()[0]
    config = _config(tmp_path)
    report = run_backup(config, _deps(config, FakeS3({"k": b"v"})))
    assert report.result == "ok"

    output = tmp_path / "bundle.age"
    write_bundle(config, Restic(config.password_file), recipient, output)
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    tar_path = tmp_path / "bundle.tar"
    subprocess.run(["age", "-d", "-i", str(identity), "-o", str(tar_path), str(output)], check=True)
    with tarfile.open(tar_path) as archive:
        names = archive.getnames()
    assert any(n.endswith(f"sets/{report.set_id}/manifest.json") for n in names)
    assert not list(config.staging_dir.glob("bundle-*")), "the scratch restore is removed"


@needs_restic
def test_bundle_needs_a_recipient_and_a_snapshot(tmp_path: Path):
    config = _config(tmp_path)
    restic = Restic(config.password_file)
    with pytest.raises(BackupError, match="recipient"):
        write_bundle(config, restic, "", tmp_path / "x")
    restic.ensure_repo(config.repository)
    with pytest.raises(BackupError, match="no snapshot"):
        write_bundle(config, restic, "age1xyz", tmp_path / "x")


# --- real pg_dump ----------------------------------------------------------------------------------------


@pytest.mark.skipif(_pg_dump_16() is None and not _TOOLS_REQUIRED, reason="pg_dump 16+ is not installed")
def test_real_pg_dump_dumps_the_exported_snapshot(tmp_path: Path):
    config = _config(tmp_path, pg_dump=_pg_dump_16() or "pg_dump")
    out = tmp_path / "db.dump"
    with dr_backup._snapshot_session(engine) as exporter:
        snapshot = str(exporter.execute(dr_backup.text("SELECT pg_export_snapshot()")).scalar())
        dump_database(config, get_settings().database_url, snapshot, out, Redactor())
        exporter.rollback()
    assert out.stat().st_size > 1000 and stat.S_IMODE(out.stat().st_mode) == 0o600
    pg_restore = str(Path(config.pg_dump).with_name("pg_restore"))
    listing = subprocess.run([pg_restore, "--list", str(out)], capture_output=True, text=True, check=True).stdout
    assert "TABLE public alembic_version" in listing


def test_missing_pg_dump_binary_is_a_clear_failure(tmp_path: Path):
    config = _config(tmp_path, pg_dump=str(tmp_path / "absent"))
    with pytest.raises(BackupError, match="cannot run pg_dump"):
        dump_database(config, "postgresql://u:p@h/d", "00000003-0000001B-1", tmp_path / "x", Redactor())


# --- configuration and CLI -------------------------------------------------------------------------------


def test_destinations_split_on_commas_and_newlines(tmp_path: Path):
    config = _config(tmp_path, destinations_raw="s3:https://a/b,\n sftp:u@h:/p ,,")
    assert config.destinations == ["s3:https://a/b", "sftp:u@h:/p"]


def test_check_subset_rejects_arbitrary_options(tmp_path: Path):
    with pytest.raises(ValueError):
        _config(tmp_path, check_subset="5%; rm -rf /")


def test_cli_exits_75_when_a_backup_is_already_running(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import importlib.util

    spec = importlib.util.spec_from_file_location("dr_backup_cli", _SCRIPTS / "dr_backup.py")
    assert spec and spec.loader
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    config = _config(tmp_path)
    monkeypatch.setenv("BACKUP_STAGING_DIR", str(config.staging_dir))
    monkeypatch.setenv("BACKUP_PASSWORD_FILE", str(config.password_file))
    monkeypatch.setenv("BACKUP_REPOSITORY", config.repository)
    monkeypatch.setenv("BACKUP_STATUS_DIR", str(config.status_dir))
    monkeypatch.setenv("BACKUP_SECRETS_MODE", "none")
    with run_lock(config.staging_dir):
        assert cli.main(["run"]) == dr_backup.EX_TEMPFAIL


def test_cli_rejects_invalid_configuration(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]):
    import importlib.util

    spec = importlib.util.spec_from_file_location("dr_backup_cli2", _SCRIPTS / "dr_backup.py")
    assert spec and spec.loader
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    monkeypatch.setenv("BACKUP_SECRETS_MODE", "sometimes")
    assert cli.main(["run"]) == 2
    assert "invalid backup configuration" in capsys.readouterr().err
