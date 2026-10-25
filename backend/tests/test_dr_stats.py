"""Tests for the disaster-recovery statistics document (`services.dr_stats`), the backup manifest
(`services.dr_manifest`) and the `scripts/dr_stats.py` CLI.

Each test builds its own data, so none depends on state left by another test or run; the one test that
creates a table outside the models drops it in a `finally`.
"""

from __future__ import annotations

import json
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from botocore.exceptions import ClientError
from sqlalchemy import select, text

from app.config import get_settings
from app.database import Base, SessionLocal, engine
from app.models.file import FileAsset
from app.models.organization import Organization
from app.models.user import User
from app.services import dr_stats
from app.services.dr_manifest import (
    MANIFEST_VERSION,
    BackupManifest,
    ComponentKind,
    dump_manifest,
    load_manifest,
    manifest_json_schema,
)
from app.storage_backends import LocalFileStorageBackend, S3CompatibleFileStorageBackend
from tests.link_world import REQ, World

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
_SCHEMA_FILE = Path(__file__).resolve().parents[2] / "docs" / "schemas" / "backup-manifest.schema.json"


class FakeStorage:
    """A storage backend holding a fixed key set, for the file probe."""

    name = "s3"

    def __init__(self, keys: set[str]) -> None:
        self.keys = keys

    def exists(self, key: str) -> bool:
        return key in self.keys


def _collect(storage=None, snapshot_id: str | None = None) -> dr_stats.DrStats:
    """Collects stats in a fresh session and closes it."""
    with SessionLocal() as db:
        try:
            return dr_stats.collect_stats(db, storage, snapshot_id=snapshot_id)
        finally:
            db.rollback()


def _file_asset(db, organization_id, uploaded_by, key: str, backend: str = "s3", size: int = 10) -> uuid.UUID:
    asset = FileAsset(
        organization_id=organization_id,
        storage_backend=backend,
        storage_key=key,
        filename="f.txt",
        content_type="text/plain",
        size_bytes=size,
        uploaded_by=uploaded_by,
    )
    db.add(asset)
    db.flush()
    return asset.id


@pytest.fixture
def world(client, admin_token) -> World:
    return World(client, admin_token, "DR Org", context_strategy=True)


def test_every_model_table_and_the_alembic_revision_are_counted(client):
    stats = _collect()
    missing = {t.name for t in Base.metadata.sorted_tables} - set(stats.tables)
    assert not missing, f"tables skipped by dr_stats: {sorted(missing)}"
    assert stats.alembic_revision
    assert stats.tables["alembic_version"] == 1
    assert stats.business.users.server_admins >= 1  # the bootstrapped server admin


def test_business_counts_match_what_was_created(world):
    project = world.project("Alpha")
    world.requirement(project, "One")
    world.requirement(project, "Two")
    world.action(project, "Do it")
    world.pain_point(project)
    stats = _collect()
    business = stats.business
    assert business.organizations >= 1
    assert business.projects == 1
    assert business.records[REQ] == 2
    assert business.records["requirement_action"] == 1
    assert business.records["pain_point"] == 1
    assert business.users.total == business.users.active + business.users.inactive
    assert business.uncounted_types == []


def test_table_added_outside_the_models_is_counted(client):
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE dr_test_extra (n int)"))
        conn.execute(text("INSERT INTO dr_test_extra VALUES (1), (2), (3)"))
    try:
        assert _collect().tables["dr_test_extra"] == 3
    finally:
        with engine.begin() as conn:
            conn.execute(text("DROP TABLE dr_test_extra"))


def test_snapshot_pins_the_view_while_the_data_changes(client):
    holder = engine.connect()
    try:
        holder.execute(text("BEGIN ISOLATION LEVEL REPEATABLE READ"))
        snapshot_id = holder.execute(text("SELECT pg_export_snapshot()")).scalar_one()
        before = _collect()
        with SessionLocal() as db:
            db.add(Organization(name=f"Late {uuid.uuid4().hex[:6]}", slug=f"late-{uuid.uuid4().hex[:8]}"))
            db.commit()
        pinned = _collect(snapshot_id=snapshot_id)
        live = _collect()
    finally:
        holder.rollback()
        holder.close()
    assert dr_stats.compare_stats(before, pinned) == []
    assert live.business.organizations == before.business.organizations + 1
    assert live.tables["organizations"] == pinned.tables["organizations"] + 1


def test_snapshot_id_is_validated_before_it_reaches_sql(client):
    with SessionLocal() as db, pytest.raises(ValueError):
        dr_stats.collect_stats(db, None, snapshot_id="1'; DROP TABLE users; --")


def test_file_probe_names_missing_records_by_id_only(client):
    with SessionLocal() as db:
        org = db.scalars(select(Organization)).first() or Organization(name="O", slug=f"o-{uuid.uuid4().hex[:8]}")
        db.add(org)
        db.flush()
        admin = db.scalars(select(User).where(User.is_server_admin.is_(True))).first()
        present = _file_asset(db, org.id, admin.id, "org/present_secret-name.txt")
        absent = _file_asset(db, org.id, admin.id, "org/absent_secret-name.txt")
        _file_asset(db, org.id, admin.id, "elsewhere", backend="local")
        db.commit()
        del present
    stats = _collect(FakeStorage({"org/present_secret-name.txt"}))
    probe = stats.probes.files
    assert (probe.checked, probe.missing, probe.other_backend) == (2, 1, 1)
    assert probe.missing_file_ids == [str(absent)]
    assert "secret-name" not in stats.model_dump_json()
    assert any("1 of 2 file records" in line for line in dr_stats.probe_failures(stats))
    assert stats.business.files.records == 3 and stats.business.files.bytes == 30


def test_file_probe_is_skipped_without_storage(client):
    probe = _collect(None).probes.files
    assert probe.skipped and probe.checked == 0


def test_encrypted_columns_are_probed_and_a_wrong_key_is_reported(client):
    with SessionLocal() as db:
        org = Organization(name="Enc", slug=f"enc-{uuid.uuid4().hex[:8]}", smtp_password="hunter2-sentinel")
        db.add(org)
        db.commit()
    assert "organizations.smtp_password" in {f"{t}.{c}" for t, c in dr_stats.encrypted_columns()}
    healthy = _collect()
    column = healthy.probes.encrypted_columns["organizations.smtp_password"]
    assert (column.rows, column.undecryptable) == (1, 0)
    assert dr_stats.probe_failures(healthy) == []

    settings = get_settings()
    original = settings.app_secret_encryption_key
    settings.app_secret_encryption_key = "a-different-key"
    try:
        wrong = _collect()
    finally:
        settings.app_secret_encryption_key = original
    assert wrong.probes.encrypted_columns["organizations.smtp_password"].undecryptable == 1
    failures = dr_stats.probe_failures(wrong)
    assert failures and "organizations.smtp_password" in failures[0]
    assert "hunter2-sentinel" not in wrong.model_dump_json()


def test_encryption_probe_can_be_left_out_when_the_caller_has_no_key(client):
    with SessionLocal() as db:
        db.add(Organization(name="NoKey", slug=f"nokey-{uuid.uuid4().hex[:8]}", smtp_password="hunter2-sentinel"))
        db.commit()
        try:
            stats = dr_stats.collect_stats(db, None, probe_encryption=False)
        finally:
            db.rollback()
    assert stats.probes.encrypted_columns == {}
    assert dr_stats.probe_failures(stats) == []


def test_document_holds_no_row_content(world):
    project = world.project("Sentinel-Project-Name")
    world.requirement(project, "Sentinel-Requirement-Title")
    document = _collect().model_dump_json()
    for sentinel in ("Sentinel-Project-Name", "Sentinel-Requirement-Title", "admin@example.com", world.org["name"]):
        assert sentinel not in document


def test_compare_reports_each_difference_by_path(client):
    base = _collect()
    assert dr_stats.compare_stats(base, base.model_copy(deep=True)) == []
    changed = base.model_copy(deep=True)
    changed.tables["users"] += 1
    changed.business.records[REQ] = changed.business.records.get(REQ, 0) + 5
    del changed.tables["file_assets"]
    changed.alembic_revision = "9999"
    paths = {m.path: m for m in dr_stats.compare_stats(base, changed)}
    assert set(paths) == {"tables.users", f"business.records.{REQ}", "tables.file_assets", "alembic_revision"}
    assert paths["tables.file_assets"].actual is None
    other_version = base.model_copy(update={"stats_version": base.stats_version + 1})
    with pytest.raises(ValueError):
        dr_stats.compare_stats(base, other_version)


def test_comparison_ignores_probe_differences(client):
    base = _collect()
    probed = base.model_copy(deep=True)
    probed.probes.files.missing = 4
    assert dr_stats.compare_stats(base, probed) == []


# --- storage backends ---------------------------------------------------------------------------


def test_local_backend_exists(tmp_path):
    backend = LocalFileStorageBackend(str(tmp_path))
    backend.save("org/a.txt", b"x")
    assert backend.exists("org/a.txt")
    assert not backend.exists("org/b.txt")
    with pytest.raises(ValueError):
        backend.exists("../escape")


def _s3_with_head(result) -> S3CompatibleFileStorageBackend:
    backend = S3CompatibleFileStorageBackend.__new__(S3CompatibleFileStorageBackend)
    backend._bucket = "b"
    backend._client = MagicMock()
    backend._client.head_object.side_effect = result
    return backend


def test_s3_backend_exists_distinguishes_absent_from_failure():
    assert _s3_with_head(None).exists("k")
    assert not _s3_with_head(ClientError({"Error": {"Code": "404"}}, "HeadObject")).exists("k")
    with pytest.raises(ClientError):
        _s3_with_head(ClientError({"Error": {"Code": "403"}}, "HeadObject")).exists("k")


# --- manifest -----------------------------------------------------------------------------------


def _manifest(stats: dr_stats.DrStats, **overrides) -> BackupManifest:
    fields = {
        "set_id": "20261024T020000Z",
        "created_at": datetime(2026, 10, 24, 2, 0, tzinfo=UTC),
        "finished_at": datetime(2026, 10, 24, 2, 5, tzinfo=UTC),
        "tool_version": "1",
        "app": {"version": "1.2.3", "git_sha": "abc123"},
        "alembic_revision": stats.alembic_revision,
        "postgres_version": "16.4",
        "storage_backend": "s3",
        "secrets_mode": "none",
        "components": {ComponentKind.DATABASE: {"path": "db/reqtrack.dump", "sha256": "a" * 64, "bytes": 5}},
        "stats": stats,
    }
    fields.update(overrides)
    return BackupManifest.model_validate(fields)


def test_manifest_round_trips_with_its_stats(client):
    manifest = _manifest(_collect())
    text_ = dump_manifest(manifest)
    assert load_manifest(text_) == manifest
    assert json.loads(text_)["manifest_version"] == MANIFEST_VERSION
    assert "none" == json.loads(text_)["secrets_mode"]


def test_manifest_refuses_a_newer_format_bad_paths_and_naive_times(client):
    stats = _collect()
    raw = json.loads(dump_manifest(_manifest(stats)))
    with pytest.raises(ValueError, match="newer"):
        load_manifest(json.dumps({**raw, "manifest_version": MANIFEST_VERSION + 1}))
    with pytest.raises(ValueError):
        load_manifest("not json")
    for bad in ("/etc/passwd", "a/../../b", "a\\b"):
        with pytest.raises(ValueError):
            _manifest(stats, components={ComponentKind.DATABASE: {"path": bad, "sha256": "a" * 64, "bytes": 1}})
    with pytest.raises(ValueError):
        _manifest(stats, created_at=datetime(2026, 10, 24, 2, 0))
    with pytest.raises(ValueError):
        _manifest(stats, set_id="not-a-set-id")
    with pytest.raises(ValueError):
        _manifest(stats, secrets_mode="vault")


@pytest.mark.skipif(not _SCHEMA_FILE.is_file(), reason="repository docs not visible (the backend container mounts only backend/)")
def test_committed_schema_matches_the_models():
    committed = json.loads(_SCHEMA_FILE.read_text())
    regenerate = "python scripts/dr_stats.py --manifest-schema > ../docs/schemas/backup-manifest.schema.json"
    assert committed == manifest_json_schema(), f"regenerate with: {regenerate}"


# --- CLI ----------------------------------------------------------------------------------------


@pytest.fixture
def cli():
    sys.path.insert(0, str(_SCRIPTS))
    try:
        import dr_stats as script

        yield script
    finally:
        sys.path.remove(str(_SCRIPTS))
        sys.modules.pop("dr_stats", None)


def test_cli_compare_exit_codes(client, cli, tmp_path, capsys):
    stats = _collect()
    expected = tmp_path / "stats.json"
    expected.write_text(stats.model_dump_json())
    assert cli.main(["--compare", str(expected), "--no-storage-probe"]) == 0
    capsys.readouterr()

    drifted = json.loads(expected.read_text())
    drifted["tables"]["users"] += 1
    expected.write_text(json.dumps(drifted))
    assert cli.main(["--compare", str(expected), "--no-storage-probe"]) == 1
    assert "MISMATCH tables.users" in capsys.readouterr().err

    manifest_file = tmp_path / "manifest.json"
    manifest_file.write_text(dump_manifest(_manifest(stats)))
    assert cli.main(["--compare", str(manifest_file), "--no-storage-probe"]) == 0

    expected.write_text("not json")
    assert cli.main(["--compare", str(expected), "--no-storage-probe"]) == 2


def test_cli_prints_the_schema(cli, capsys):
    assert cli.main(["--manifest-schema"]) == 0
    assert json.loads(capsys.readouterr().out)["title"] == "ReqTrack backup set manifest"
