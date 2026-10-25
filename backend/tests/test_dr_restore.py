"""Tests for the disaster-recovery restore tool.

The database tests run the whole chain on real PostgreSQL: a backup of the test database with the real
`pg_dump` (read-only, taken in an exported snapshot), then a restore with the real `pg_restore` into
throwaway databases that each test creates and drops. The shared test database is only ever read. The object
store is a fake. Tests that need `restic`, `age`, `pg_dump`/`pg_restore` or the ability to create databases
skip when those are absent; CI installs them and sets `REQUIRE_DR_TOOLS=1` so a missing tool fails instead.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import tarfile
import uuid
from collections import namedtuple
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from app.config import get_settings
from app.models.user import User
from app.services import dr_restore
from app.services.dr_backup import AlreadyRunning, BackupConfig, run_backup, run_lock
from app.services.dr_manifest import ComponentKind, SecretsMode
from app.services.dr_restic import Redactor, Restic
from app.services.dr_restore import (
    REPORT_FILENAME,
    RestoreDeps,
    RestoreError,
    RestoreMode,
    RestoreOptions,
    compatibility_problems,
    config_snapshot_label,
    decrypt_config,
    extract_local_files,
    list_sets,
    read_manifest,
    resolve_set,
    restore_dump,
    run_restore,
    swap_databases,
    upload_objects,
    verify_components,
)
from tests.test_dr_backup import FakeS3, _all_bytes, _config, _deps, _pg_dump_16

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
_TOOLS_REQUIRED = os.environ.get("REQUIRE_DR_TOOLS") == "1"
needs_restic = pytest.mark.skipif(shutil.which("restic") is None and not _TOOLS_REQUIRED, reason="restic is not installed")
needs_age = pytest.mark.skipif(
    (shutil.which("age") is None or shutil.which("age-keygen") is None) and not _TOOLS_REQUIRED, reason="age is not installed"
)
needs_pg = pytest.mark.skipif(_pg_dump_16() is None and not _TOOLS_REQUIRED, reason="pg_dump/pg_restore 16+ are not installed")


DiskUsage = namedtuple("DiskUsage", "total used free")


# --- fakes and helpers -------------------------------------------------------------------------------


class FakeStore:
    """The slice of a boto3 S3 client the restore uses: bucket check and creation, put and head."""

    def __init__(self, *, bucket_exists: bool = True, wrong_size: bool = False) -> None:
        self.objects: dict[str, bytes] = {}
        self.bucket_exists = bucket_exists
        self.created = False
        self.wrong_size = wrong_size

    def head_bucket(self, Bucket: str) -> None:
        if not self.bucket_exists:
            raise RuntimeError("no such bucket")

    def create_bucket(self, Bucket: str) -> None:
        self.bucket_exists, self.created = True, True

    def put_object(self, Bucket: str, Key: str, Body: Any, ContentLength: int) -> None:
        self.objects[Key] = Body.read()

    def head_object(self, Bucket: str, Key: str) -> dict[str, int]:
        return {"ContentLength": len(self.objects[Key]) + (1 if self.wrong_size else 0)}


def _maintenance_engine(autocommit: bool = True) -> Any:
    url = make_url(get_settings().database_url).set(database="postgres")
    return create_engine(url, poolclass=NullPool, isolation_level="AUTOCOMMIT" if autocommit else "READ COMMITTED")


@pytest.fixture
def make_database() -> Iterator[Callable[[], str]]:
    """Creates empty throwaway databases and returns their URLs; drops them all afterwards.

    Skips the test when the test role cannot create databases.
    """
    created: list[str] = []
    admin = _maintenance_engine()

    def make() -> str:
        name = f"drt_{uuid.uuid4().hex[:12]}"
        try:
            with admin.connect() as conn:
                conn.execute(text(f'CREATE DATABASE "{name}"'))
        except SQLAlchemyError:
            pytest.skip("the test role cannot create databases")
        created.append(name)
        return make_url(get_settings().database_url).set(database=name).render_as_string(hide_password=False)

    yield make
    with admin.connect() as conn:
        for name in created:
            leftovers = conn.execute(text("SELECT datname FROM pg_database WHERE starts_with(datname, :n)"), {"n": name}).scalars().all()
            for leftover in leftovers:
                conn.execute(text(f'DROP DATABASE IF EXISTS "{leftover}" WITH (FORCE)'))
    admin.dispose()


def _database_names(prefix: str) -> list[str]:
    engine = _maintenance_engine()
    try:
        with engine.connect() as conn:
            return list(conn.execute(text("SELECT datname FROM pg_database WHERE starts_with(datname, :p) ORDER BY 1"), {"p": prefix}).scalars())
    finally:
        engine.dispose()


def _real_config(tmp_path: Path, **overrides: Any) -> BackupConfig:
    overrides.setdefault("local_files_dir", tmp_path / "local_target")
    return _config(tmp_path, pg_dump=_pg_dump_16() or "pg_dump", **overrides)


def _real_backup(config: BackupConfig, s3: FakeS3 | None = None, *, backend: str = "s3", **overrides: Any) -> str:
    """Backs the test database up with the real `pg_dump`; returns the set id."""
    from app.services.dr_backup import dump_database

    report = run_backup(config, _deps(config, s3 or FakeS3({}), backend=backend, dumper=dump_database, **overrides))
    assert report.result == "ok", report.error
    return report.set_id


def _restore_deps(config: BackupConfig, db_url: str, store: FakeStore | None = None, **overrides: Any) -> RestoreDeps:
    values: dict[str, Any] = {
        "db_url": db_url,
        "restic": Restic(config.password_file, redactor=Redactor(["hunter2-secret"]), probe_timeout=5),
        "storage_backend": "s3",
        "storage_client": store if store is not None else FakeStore(),
        "storage_bucket": "bucket",
        "probe_storage": None,
        "now": lambda: datetime(2026, 10, 24, 3, 0, 0, tzinfo=UTC),
        "sleep": lambda _s: None,
    }
    values.update(overrides)
    return RestoreDeps(**values)


def _tables(db_url: str) -> set[str]:
    engine = create_engine(db_url, poolclass=NullPool)
    try:
        with engine.connect() as conn:
            return set(conn.execute(text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")).scalars())
    finally:
        engine.dispose()


def _count(db_url: str, table: str) -> int:
    engine = create_engine(db_url, poolclass=NullPool)
    try:
        with engine.connect() as conn:
            return conn.execute(text(f'SELECT count(*) FROM "{table}"')).scalar_one()
    finally:
        engine.dispose()


# --- pure guards -------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def sample_manifest(tmp_path_factory: pytest.TempPathFactory):
    """A real manifest (taken from the test database with a fake dump) to vary in the guard tests."""
    if shutil.which("restic") is None and not _TOOLS_REQUIRED:
        pytest.skip("restic is not installed")
    tmp = tmp_path_factory.mktemp("manifest")
    config = _config(tmp)
    report = run_backup(config, _deps(config, FakeS3({"k": b"v"})))
    assert report.result == "ok", report.error
    restic = Restic(config.password_file)
    info = list_sets(restic, config.repository)[0]
    return read_manifest(restic, config.repository, info)


def _problems(manifest, **overrides: Any) -> list[str]:
    values: dict[str, Any] = {
        "server_major": 16,
        "known_revisions": {manifest.alembic_revision, "older"},
        "head_revisions": {manifest.alembic_revision},
        "storage_backend": manifest.storage_backend,
    }
    values.update(overrides)
    return compatibility_problems(manifest, **values)


@needs_restic
def test_a_matching_target_has_no_problems(sample_manifest):
    assert _problems(sample_manifest) == []


@needs_restic
def test_a_set_newer_than_the_image_is_refused_naming_the_image_to_use(sample_manifest):
    (problem,) = _problems(sample_manifest, known_revisions={"older"}, head_revisions={"older"})
    assert "newer than this image knows" in problem and sample_manifest.app.version in problem


@needs_restic
def test_a_set_older_than_the_image_is_refused_with_the_upgrade_path(sample_manifest):
    (problem,) = _problems(sample_manifest, head_revisions={"newer"}, known_revisions={sample_manifest.alembic_revision, "newer"})
    assert "older than this image's" in problem and "migrates the database when it starts" in problem


@needs_restic
def test_a_dump_from_a_newer_server_and_a_storage_mismatch_are_refused(sample_manifest):
    problems = _problems(sample_manifest, server_major=14, storage_backend="local" if sample_manifest.storage_backend == "s3" else "s3")
    assert len(problems) == 2
    assert any("older server" in p for p in problems) and any("STORAGE_BACKEND" in p for p in problems)


# --- sets ----------------------------------------------------------------------------------------------


@needs_restic
def test_sets_are_listed_newest_first_and_selected_by_id_prefix_or_latest(tmp_path: Path):
    config = _config(tmp_path)
    ids = []
    for hour in (2, 5):
        clock = datetime(2026, 10, 24, hour, 0, 0, tzinfo=UTC)
        deps = _deps(config, FakeS3({"k": b"v"}), now=lambda c=clock: c)
        report = run_backup(config, deps)
        assert report.result == "ok", report.error
        ids.append(report.set_id)
    restic = Restic(config.password_file)
    sets = list_sets(restic, config.repository)
    assert [s.set_id for s in sets] == sorted(ids, reverse=True)
    assert resolve_set(sets, "latest").set_id == ids[1]
    assert resolve_set(sets, ids[0]).set_id == ids[0]
    assert resolve_set(sets, sets[1].snapshot_id[:10]).set_id == sets[1].set_id
    with pytest.raises(RestoreError, match="no set matches"):
        resolve_set(sets, "20200101T000000Z")
    with pytest.raises(RestoreError, match="no backup sets"):
        resolve_set([], "latest")


@needs_restic
def test_manifest_is_read_without_restoring_the_set(tmp_path: Path):
    config = _config(tmp_path)
    run_backup(config, _deps(config, FakeS3({"k": b"v"})))
    restic = Restic(config.password_file)
    info = list_sets(restic, config.repository)[0]
    manifest = read_manifest(restic, config.repository, info)
    assert manifest.set_id == info.set_id and manifest.storage_backend == "s3"


# --- components and files --------------------------------------------------------------------------------


@needs_restic
def test_a_damaged_component_fails_the_checksum_step_before_anything_is_changed(tmp_path: Path):
    config = _config(tmp_path)
    run_backup(config, _deps(config, FakeS3({"k": b"v"})))
    restic = Restic(config.password_file)
    info = list_sets(restic, config.repository)[0]
    manifest = read_manifest(restic, config.repository, info)
    restic.restore(config.repository, info.snapshot_id, tmp_path / "fetched")
    set_dir = tmp_path / "fetched" / info.set_path.lstrip("/")
    objects_dir = tmp_path / "fetched" / (info.objects_path or "").lstrip("/")
    verify_components(manifest, set_dir, objects_dir)

    dump = set_dir / manifest.components[ComponentKind.DATABASE].path
    original = dump.read_bytes()
    dump.write_bytes(original + b"x")
    with pytest.raises(RestoreError, match="database component does not match"):
        verify_components(manifest, set_dir, objects_dir)
    dump.unlink()
    with pytest.raises(RestoreError, match="database component is missing"):
        verify_components(manifest, set_dir, objects_dir)
    dump.write_bytes(original)
    shutil.rmtree(objects_dir)
    with pytest.raises(RestoreError, match="object mirror holds 0 objects"):
        verify_components(manifest, set_dir, objects_dir)


def test_upload_puts_every_object_under_its_key_and_creates_a_missing_bucket(tmp_path: Path):
    root = tmp_path / "objects"
    (root / "org/a").mkdir(parents=True)
    (root / "org/a/file1").write_bytes(b"first")
    (root / "top").write_bytes(b"second")
    store = FakeStore(bucket_exists=False)
    assert upload_objects(store, "bucket", root) == 2
    assert store.objects == {"org/a/file1": b"first", "top": b"second"} and store.created


def test_upload_fails_on_a_wrong_stored_size_without_naming_the_key(tmp_path: Path):
    root = tmp_path / "objects"
    root.mkdir()
    (root / "secret-customer-name.pdf").write_bytes(b"data")
    with pytest.raises(RestoreError) as caught:
        upload_objects(FakeStore(wrong_size=True), "bucket", root)
    assert "wrong size" in str(caught.value) and "secret-customer-name" not in str(caught.value)


def test_upload_refuses_a_symbolic_link(tmp_path: Path):
    root = tmp_path / "objects"
    root.mkdir()
    (root / "link").symlink_to("/etc/passwd")
    with pytest.raises(RestoreError, match="symbolic link"):
        upload_objects(FakeStore(), "bucket", root)


def _tar(path: Path, members: list[tuple[str, bytes | None, str]]) -> None:
    """Writes a tar; each member is `(name, content, kind)` with kind `file`, `dir`, `link` or `dev`."""
    with tarfile.open(path, "w") as archive:
        for name, content, kind in members:
            info = tarfile.TarInfo(name)
            if kind == "dir":
                info.type = tarfile.DIRTYPE
                archive.addfile(info)
            elif kind == "link":
                info.type, info.linkname = tarfile.SYMTYPE, "/etc/passwd"
                archive.addfile(info)
            elif kind == "dev":
                info.type = tarfile.CHRTYPE
                archive.addfile(info)
            else:
                data = content or b""
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))


def test_local_files_are_unpacked_without_the_files_prefix(tmp_path: Path):
    archive = tmp_path / "files.tar"
    _tar(archive, [("files", None, "dir"), ("files/org", None, "dir"), ("files/org/a.txt", b"hello", "file")])
    dest = tmp_path / "dest"
    assert extract_local_files(archive, dest) == 1
    assert (dest / "org" / "a.txt").read_bytes() == b"hello"


@pytest.mark.parametrize(
    "members",
    [
        [("files/../escape", b"x", "file")],
        [("/abs/file", b"x", "file")],
        [("other/file", b"x", "file")],
        [("files/link", None, "link")],
        [("files/dev", None, "dev")],
    ],
    ids=["traversal", "absolute", "outside-root", "symlink", "device"],
)
def test_local_files_archive_with_an_unsafe_member_is_refused(tmp_path: Path, members: list[tuple[str, bytes | None, str]]):
    archive = tmp_path / "files.tar"
    _tar(archive, members)
    with pytest.raises(RestoreError):
        extract_local_files(archive, tmp_path / "dest")
    assert not (tmp_path / "escape").exists()


# --- pg_restore ------------------------------------------------------------------------------------------


def test_pg_restore_failure_reports_only_its_own_lines_never_row_data(tmp_path: Path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "pg_dump").write_text("#!/bin/sh\n")
    fake = bin_dir / "pg_restore"
    fake.write_text(
        "#!/bin/sh\n"
        'echo "pg_restore: error: could not execute query: ERROR:  duplicate key" >&2\n'
        'echo "DETAIL:  Key (email)=(SENTINEL-ROW-VALUE) already exists." >&2\n'
        'echo "Command was: COPY public.users FROM stdin; SENTINEL-COPY-DATA" >&2\n'
        "exit 1\n"
    )
    fake.chmod(0o755)
    config = _config(tmp_path, pg_dump=str(bin_dir / "pg_dump"))
    with pytest.raises(RestoreError) as caught:
        restore_dump(config, "postgresql://u:p@h/d", tmp_path / "x.dump", Redactor())
    message = str(caught.value)
    assert "duplicate key" in message and "SENTINEL" not in message
    assert caught.value.step == "database"


def test_missing_pg_restore_binary_is_a_clear_failure(tmp_path: Path):
    config = _config(tmp_path, pg_dump=str(tmp_path / "absent" / "pg_dump"))
    with pytest.raises(RestoreError, match="cannot run pg_restore"):
        restore_dump(config, "postgresql://u:p@h/d", tmp_path / "x.dump", Redactor())


# --- swap ------------------------------------------------------------------------------------------------


@needs_pg
def test_a_failed_second_rename_puts_the_live_database_back(make_database: Callable[[], str]):
    live_url = make_database()
    live = make_url(live_url).database
    assert live
    engine = create_engine(live_url, poolclass=NullPool)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE marker (id int)"))
    engine.dispose()
    admin = _maintenance_engine()
    try:
        with pytest.raises(RestoreError, match="live database is unchanged"):
            swap_databases(admin, live=live, new="drt_does_not_exist", keep_old_as=f"{live}_pre_restore_x", sleep=lambda _s: None)
    finally:
        admin.dispose()
    assert "marker" in _tables(live_url), "the live database must still be reachable under its own name"
    assert _database_names(f"{live}_pre_restore") == []


# --- end to end on real PostgreSQL -----------------------------------------------------------------------


@needs_restic
@needs_pg
def test_fresh_restore_rebuilds_the_database_and_objects_and_verifies_against_the_manifest(tmp_path: Path, make_database: Callable[[], str]):
    config = _real_config(tmp_path)
    s3 = FakeS3({"org/a/file1": b"first file", "org/b/file2": b"second file"})
    set_id = _real_backup(config, s3)
    target = make_database()
    store = FakeStore()

    report = run_restore(config, _restore_deps(config, target, store), RestoreOptions(mode=RestoreMode.FRESH))
    assert report.result == "ok", (report.step, report.error)
    assert report.set_id == set_id and report.objects_restored == 2 and report.previous_database is None
    assert store.objects == {"org/a/file1": b"first file", "org/b/file2": b"second file"}
    assert "alembic_version" in _tables(target) and "users" in _tables(target)

    restic = Restic(config.password_file)
    manifest = read_manifest(restic, config.repository, list_sets(restic, config.repository)[0])
    assert _count(target, "users") == manifest.stats.tables["users"]
    assert _count(target, "alembic_version") == 1

    name = make_url(target).database
    assert _database_names(f"{name}_restore") == [], "the scratch database must be gone"
    assert not list(config.staging_dir.glob("restore-*")), "the fetched, unencrypted set must be removed"
    document = json.loads((config.status_dir / REPORT_FILENAME).read_text())
    assert document["result"] == "ok" and document["step"] == "done"


@needs_restic
@needs_pg
def test_dry_run_checks_the_guards_and_changes_nothing(tmp_path: Path, make_database: Callable[[], str]):
    config = _real_config(tmp_path)
    _real_backup(config, FakeS3({"k": b"v"}))
    target = make_database()
    store = FakeStore()
    report = run_restore(config, _restore_deps(config, target, store), RestoreOptions(mode=RestoreMode.FRESH, dry_run=True))
    assert report.result == "dry-run", (report.step, report.error)
    assert report.plan and any("organisations" in line for line in report.plan)
    assert _tables(target) == set() and store.objects == {}
    assert not config.staging_dir.joinpath(f"restore-{report.set_id}").exists()
    assert not (config.status_dir / REPORT_FILENAME).exists(), "a dry run must not replace the record of the last real restore"
    assert _database_names(f"{make_url(target).database}_restore") == []


@needs_restic
@needs_pg
def test_fresh_restore_refuses_a_database_that_already_holds_data(tmp_path: Path, make_database: Callable[[], str]):
    config = _real_config(tmp_path)
    _real_backup(config, FakeS3({"k": b"v"}))
    target = make_database()
    engine = create_engine(target, poolclass=NullPool)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE precious (id int)"))
        conn.execute(text("INSERT INTO precious VALUES (1)"))
    engine.dispose()
    store = FakeStore()
    report = run_restore(config, _restore_deps(config, target, store), RestoreOptions(mode=RestoreMode.FRESH))
    assert report.result == "failed" and report.step == "plan" and "already holds data" in (report.error or "")
    assert _tables(target) == {"precious"} and _count(target, "precious") == 1 and store.objects == {}


@needs_restic
@needs_pg
def test_in_place_restore_needs_confirmation_then_keeps_the_previous_database(tmp_path: Path, make_database: Callable[[], str]):
    config = _real_config(tmp_path)
    _real_backup(config, FakeS3({"k": b"v"}))
    target = make_database()
    engine = create_engine(target, poolclass=NullPool)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE precious (id int)"))
    engine.dispose()
    name = make_url(target).database

    explicit_report = tmp_path / "explicit-report.json"
    refused = run_restore(config, _restore_deps(config, target), RestoreOptions(mode=RestoreMode.IN_PLACE, report_path=explicit_report))
    assert refused.result == "failed" and "--yes" in (refused.error or "")
    assert _tables(target) == {"precious"}
    assert json.loads(explicit_report.read_text())["step"] == "plan" and not (config.status_dir / REPORT_FILENAME).exists()

    report = run_restore(config, _restore_deps(config, target), RestoreOptions(mode=RestoreMode.IN_PLACE, confirmed=True))
    assert report.result == "ok", (report.step, report.error)
    assert "users" in _tables(target) and "precious" not in _tables(target)
    assert report.previous_database == f"{name}_pre_restore_20261024t030000z"
    previous_url = make_url(target).set(database=report.previous_database).render_as_string(hide_password=False)
    assert _tables(previous_url) == {"precious"}, "the replaced database is kept intact for rollback"


@needs_restic
@needs_pg
def test_a_failed_verification_leaves_the_live_database_untouched(tmp_path: Path, make_database: Callable[[], str], monkeypatch: pytest.MonkeyPatch):
    config = _real_config(tmp_path)
    _real_backup(config, FakeS3({"k": b"v"}))
    target = make_database()
    engine = create_engine(target, poolclass=NullPool)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE precious (id int)"))
    engine.dispose()

    real_collect = dr_restore.collect_stats

    def wrong_counts(*args: Any, **kwargs: Any):
        stats = real_collect(*args, **kwargs)
        stats.tables["users"] += 1
        return stats

    monkeypatch.setattr(dr_restore, "collect_stats", wrong_counts)
    report = run_restore(config, _restore_deps(config, target), RestoreOptions(mode=RestoreMode.IN_PLACE, confirmed=True))
    assert report.result == "failed" and report.step == "verify" and "statistics differ" in (report.error or "")
    assert report.mismatches and report.mismatches[0]["path"] == "tables.users"
    assert _tables(target) == {"precious"}, "a restore that does not verify must not replace anything"
    assert _database_names(f"{make_url(target).database}_restore") == []
    assert not list(config.staging_dir.glob("restore-*"))


@needs_restic
@needs_pg
def test_a_dump_pg_restore_rejects_leaves_the_target_empty_and_leaks_nothing(tmp_path: Path, make_database: Callable[[], str]):
    config = _real_config(tmp_path)
    garbage = b"SENTINEL-ROW-VALUE"
    report = run_backup(config, _deps(config, FakeS3({"k": b"v"}), dumper=lambda c, u, s, out, r: out.write_bytes(garbage)))
    assert report.result == "ok", report.error
    target = make_database()
    result = run_restore(config, _restore_deps(config, target), RestoreOptions(mode=RestoreMode.FRESH))
    assert result.result == "failed" and result.step == "database"
    assert "SENTINEL" not in (result.error or "") and "SENTINEL" not in (config.status_dir / REPORT_FILENAME).read_text()
    assert _tables(target) == set()
    assert _database_names(f"{make_url(target).database}_restore") == []


@needs_restic
@needs_pg
def test_not_enough_free_disk_stops_before_fetching(tmp_path: Path, make_database: Callable[[], str], monkeypatch: pytest.MonkeyPatch):
    config = _real_config(tmp_path)
    _real_backup(config, FakeS3({"k": b"v"}))
    target = make_database()
    monkeypatch.setattr(dr_restore.shutil, "disk_usage", lambda _p: DiskUsage(100, 99, 1))
    report = run_restore(config, _restore_deps(config, target), RestoreOptions(mode=RestoreMode.FRESH))
    assert report.result == "failed" and report.step == "download" and "not enough free space" in (report.error or "")
    assert _tables(target) == set() and not list(config.staging_dir.glob("restore-*"))


@needs_restic
@needs_pg
def test_a_running_backup_refuses_the_restore_and_leaves_the_last_report(tmp_path: Path, make_database: Callable[[], str]):
    config = _real_config(tmp_path)
    _real_backup(config, FakeS3({"k": b"v"}))
    target = make_database()
    with run_lock(config.staging_dir), pytest.raises(AlreadyRunning):
        run_restore(config, _restore_deps(config, target), RestoreOptions(mode=RestoreMode.FRESH))
    assert not (config.status_dir / REPORT_FILENAME).exists()


@needs_restic
@needs_pg
def test_local_files_backend_round_trip(tmp_path: Path, make_database: Callable[[], str]):
    source = tmp_path / "local_source"
    (source / "org").mkdir(parents=True)
    (source / "org" / "a.txt").write_bytes(b"attachment")
    config = _real_config(tmp_path, local_files_dir=source)
    _real_backup(config, None, backend="local")

    target_dir = tmp_path / "local_target"
    target = make_database()
    config = config.model_copy(update={"local_files_dir": target_dir})
    deps = _restore_deps(config, target, storage_backend="local", storage_client=None)
    report = run_restore(config, deps, RestoreOptions(mode=RestoreMode.FRESH))
    assert report.result == "ok", (report.step, report.error)
    assert (target_dir / "org" / "a.txt").read_bytes() == b"attachment" and report.objects_restored == 1


# --- secrets ---------------------------------------------------------------------------------------------


def _user_with_foreign_totp(db_url: str) -> str:
    """Adds a 2FA-enrolled user whose TOTP secret was encrypted under a different key; returns its email."""
    email = f"drt-{uuid.uuid4().hex[:8]}@example.test"
    foreign = Fernet(Fernet.generate_key()).encrypt(b"JBSWY3DPEHPK3PXP").decode()
    engine = create_engine(db_url, poolclass=NullPool)
    try:
        with Session(engine) as db:
            user = User(email=email, display_name="Enrolled", auth_backend="native")
            db.add(user)
            db.commit()
            db.execute(text("UPDATE users SET totp_secret = :c, is_2fa_enabled = true WHERE id = :i"), {"c": foreign, "i": user.id})
            db.commit()
    finally:
        engine.dispose()
    return email


@needs_restic
@needs_pg
def test_secrets_the_key_cannot_read_fail_the_restore_unless_clearing_is_asked_for(tmp_path: Path, make_database: Callable[[], str]):
    # Build a source that holds a TOTP secret from another key: restore the test data into a throwaway database,
    # add the user there, and back that database up (the source's own integrity probe is told the key is absent).
    (tmp_path / "first").mkdir()
    (tmp_path / "second").mkdir()
    first_config = _real_config(tmp_path / "first")
    _real_backup(first_config, FakeS3({}))
    source = make_database()
    assert run_restore(first_config, _restore_deps(first_config, source), RestoreOptions(mode=RestoreMode.FRESH)).result == "ok"
    email = _user_with_foreign_totp(source)

    config = _real_config(tmp_path / "second")
    source_engine = create_engine(source, poolclass=NullPool)
    from app.services.dr_backup import dump_database

    report = run_backup(config, _deps(config, FakeS3({}), engine=source_engine, db_url=source, dumper=dump_database, probe_encryption=False))
    source_engine.dispose()
    assert report.result == "ok", report.error

    refused_target = make_database()
    refused = run_restore(config, _restore_deps(config, refused_target), RestoreOptions(mode=RestoreMode.FRESH))
    assert refused.result == "failed" and refused.step == "verify"
    assert "users.totp_secret" in (refused.error or "") and "--clear-unreadable-secrets" in (refused.error or "")
    assert _tables(refused_target) == set(), "nothing is swapped in while a secret is unreadable"

    cleared_target = make_database()
    cleared = run_restore(
        config, _restore_deps(config, cleared_target, actor="cli:tester"), RestoreOptions(mode=RestoreMode.FRESH, clear_unreadable_secrets=True)
    )
    assert cleared.result == "ok", (cleared.step, cleared.error)
    assert cleared.secrets_cleared == {"users.totp_secret": 1}
    engine = create_engine(cleared_target, poolclass=NullPool)
    try:
        with engine.connect() as conn:
            row = conn.execute(text("SELECT totp_secret, is_2fa_enabled FROM users WHERE email = :e"), {"e": email}).one()
            audit = conn.execute(text("SELECT detail FROM audit_events WHERE entity_type = 'restore' AND action = 'secrets_cleared'")).scalars().all()
    finally:
        engine.dispose()
    assert row.totp_secret is None and row.is_2fa_enabled is False
    assert len(audit) == 1 and audit[0]["actor"] == "cli:tester" and audit[0]["columns"] == {"users.totp_secret": 1}
    assert "JBSWY3DPEHPK3PXP" not in json.dumps(audit)


def _add_local_user(db_url: str, *, enrolled: bool = False) -> str:
    """Adds a native user with a password hash (and optionally 2FA) to a database; returns its email."""
    email = f"drf-{uuid.uuid4().hex[:8]}@example.test"
    engine = create_engine(db_url, poolclass=NullPool)
    try:
        with Session(engine) as db:
            db.add(User(email=email, display_name="Local", auth_backend="native", password_hash="x" * 60))
            db.commit()
            if enrolled:
                db.execute(text("UPDATE users SET is_2fa_enabled = true WHERE email = :e"), {"e": email})
                db.commit()
    finally:
        engine.dispose()
    return email


@needs_restic
@needs_pg
def test_force_reset_marks_every_local_account_on_the_restored_copy_and_audits_it(tmp_path: Path, make_database: Callable[[], str]):
    (tmp_path / "first").mkdir()
    (tmp_path / "second").mkdir()
    first_config = _real_config(tmp_path / "first")
    _real_backup(first_config, FakeS3({}))
    source = make_database()
    assert run_restore(first_config, _restore_deps(first_config, source), RestoreOptions(mode=RestoreMode.FRESH)).result == "ok"
    email = _add_local_user(source, enrolled=True)
    config = _real_config(tmp_path / "second")
    source_engine = create_engine(source, poolclass=NullPool)
    from app.services.dr_backup import dump_database

    assert run_backup(config, _deps(config, FakeS3({}), engine=source_engine, db_url=source, dumper=dump_database)).result == "ok"
    source_engine.dispose()

    target = make_database()
    report = run_restore(
        config, _restore_deps(config, target, actor="cli:tester"),
        RestoreOptions(mode=RestoreMode.FRESH, force_reset="all", reset_2fa=True),
    )

    assert report.result == "ok", (report.step, report.error)
    assert report.credentials_reset["marked"] >= 1 and report.credentials_reset["two_factor_cleared"] == 1
    engine = create_engine(target, poolclass=NullPool)
    try:
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT must_reset_credentials, token_version, is_2fa_enabled FROM users WHERE email = :e"), {"e": email}
            ).one()
            audit = conn.execute(text("SELECT detail FROM audit_events WHERE action = 'credentials_force_reset'")).scalars().all()
    finally:
        engine.dispose()
    assert row.must_reset_credentials is True and row.token_version == 1 and row.is_2fa_enabled is False
    assert len(audit) == 1 and audit[0]["actor"] == "cli:tester" and audit[0]["scope"] == "all"
    assert email not in json.dumps(audit)


@needs_restic
@needs_pg
def test_an_unknown_force_reset_scope_fails_before_anything_is_swapped_in(tmp_path: Path, make_database: Callable[[], str]):
    config = _real_config(tmp_path)
    _real_backup(config, FakeS3({}))
    target = make_database()
    report = run_restore(config, _restore_deps(config, target), RestoreOptions(mode=RestoreMode.FRESH, force_reset="everyone"))
    assert report.result == "failed" and report.step == "credentials"
    assert _tables(target) == set()


@needs_restic
@needs_pg
def test_clearing_needs_a_key_to_judge_by(tmp_path: Path, make_database: Callable[[], str]):
    config = _real_config(tmp_path)
    _real_backup(config, FakeS3({}))
    target = make_database()
    deps = _restore_deps(config, target, probe_encryption=False)
    report = run_restore(config, deps, RestoreOptions(mode=RestoreMode.FRESH, clear_unreadable_secrets=True))
    assert report.result == "failed" and report.step == "plan" and "needs the key" in (report.error or "")
    assert _tables(target) == set()


# --- configuration snapshot ------------------------------------------------------------------------------


def _age_keypair(tmp_path: Path) -> tuple[Path, str]:
    identity = tmp_path / "identity.txt"
    keygen = subprocess.run(["age-keygen", "-o", str(identity)], capture_output=True, text=True, check=True)
    return identity, (keygen.stderr + keygen.stdout).split("Public key:")[1].split()[0]


@needs_restic
@needs_age
def test_the_configuration_snapshot_is_decrypted_with_the_identity(tmp_path: Path):
    identity, recipient = _age_keypair(tmp_path)
    env_file = tmp_path / "env"
    env_file.write_text("APP_SECRET_ENCRYPTION_KEY=sentinel-restore-key\nJWT_SECRET=sentinel-jwt\n")
    config = _config(tmp_path, secrets_mode=SecretsMode.CONFIG, env_file=env_file, config_age_recipient=recipient)
    assert run_backup(config, _deps(config, FakeS3({}))).result == "ok"

    restic = Restic(config.password_file)
    assert decrypt_config(config, restic, config.repository, "latest", identity) == env_file.read_bytes()

    (tmp_path / "other").mkdir()
    other, _ = _age_keypair(tmp_path / "other")
    with pytest.raises(RestoreError, match="could not decrypt"):
        decrypt_config(config, restic, config.repository, "latest", other)


@needs_restic
def test_a_set_taken_without_configuration_says_so(tmp_path: Path):
    config = _config(tmp_path, secrets_mode=SecretsMode.NONE)
    assert run_backup(config, _deps(config, FakeS3({}))).result == "ok"
    with pytest.raises(RestoreError, match="holds no configuration snapshot"):
        decrypt_config(config, Restic(config.password_file), config.repository, "latest", tmp_path / "identity")


# --- command line ----------------------------------------------------------------------------------------


def _cli():
    import importlib.util

    spec = importlib.util.spec_from_file_location(f"dr_restore_cli_{uuid.uuid4().hex[:6]}", _SCRIPTS / "dr_restore.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _cli_env(config: BackupConfig, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BACKUP_STAGING_DIR", str(config.staging_dir))
    monkeypatch.setenv("BACKUP_PASSWORD_FILE", str(config.password_file))
    monkeypatch.setenv("BACKUP_REPOSITORY", config.repository)
    monkeypatch.setenv("BACKUP_STATUS_DIR", str(config.status_dir))
    monkeypatch.setenv("BACKUP_SECRETS_MODE", "none")


@needs_restic
def test_cli_lists_the_sets(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]):
    config = _config(tmp_path)
    report = run_backup(config, _deps(config, FakeS3({"k": b"v"})))
    _cli_env(config, monkeypatch)
    assert _cli().main(["list"]) == 0
    assert report.set_id in capsys.readouterr().out


@needs_restic
@needs_age
def test_cli_config_writes_the_plain_env_to_stdout_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsysbinary: pytest.CaptureFixture[bytes]):
    identity, recipient = _age_keypair(tmp_path)
    env_file = tmp_path / "env"
    env_file.write_text("JWT_SECRET=sentinel-cli-jwt\n")
    config = _config(tmp_path, secrets_mode=SecretsMode.CONFIG, env_file=env_file, config_age_recipient=recipient)
    assert run_backup(config, _deps(config, FakeS3({}))).result == "ok"
    _cli_env(config, monkeypatch)
    assert _cli().main(["config", "--age-identity", str(identity)]) == 0
    captured = capsysbinary.readouterr()
    assert captured.out == env_file.read_bytes() and b"sentinel-cli-jwt" not in captured.err
    assert b"sentinel-cli-jwt" not in _all_bytes(config.status_dir)


@pytest.mark.parametrize(
    "mode, label",
    [
        ("config", "with config snapshot"),
        ("none", "no config snapshot"),
        ("unknown", "config snapshot unknown"),
        ("anything", "config snapshot unknown"),
    ],
)
def test_config_snapshot_label_is_a_fixed_phrase(mode: str, label: str):
    assert config_snapshot_label(mode) == label


def test_cli_rejects_invalid_configuration(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]):
    monkeypatch.setenv("BACKUP_SECRETS_MODE", "sometimes")
    assert _cli().main(["list"]) == 2
    assert "invalid configuration" in capsys.readouterr().err
