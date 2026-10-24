"""
Module: services.dr_restore

The restore run: one command that brings a backup set back as a working platform, refusing the cases that
would damage a target, and proving the result matches what was backed up before it replaces anything.

Responsibilities:
- List the sets a repository holds, resolve one (`latest`, a set id or a snapshot id) and read its manifest
  without downloading the set.
- Decide whether the set can be restored into this target (`compatibility_problems`, target state) and say so
  in a dry run.
- Fetch the set (verified against the repository), check its components against the manifest, put the objects
  back (S3 upload or local-files extract), restore the database into a scratch database, verify it with the
  same `dr_stats` code the backup used, optionally clear secrets the supplied key cannot read, and only then
  swap the scratch database in.
- Decrypt the set's age-encrypted `.env` snapshot for a fresh host (`decrypt_config`).
- Always leave a machine-readable report that holds counts and step names only.

Design decisions:
- The live database is never written to. The set is restored into `<name>_restore_<set>`, verified, then
  renamed into place; a failure at any earlier point leaves the live database exactly as it was. In place, the
  previous database is kept under a new name (rollback is a rename; deleting it is the operator's call). On a
  fresh host the verified-empty database is dropped.
- Restoring needs the image the set was taken with: the statistics are computed by the application's own
  models, which only read a database at their own schema revision. A set from another revision is refused
  with the image tag to use, rather than restored unverified.
- Objects go back before the database swap and are only ever added, so a failed run cannot lose an attachment;
  objects the set does not know are left alone (they are orphans, not data loss).
- Unreadable encrypted values (the wrong or a replacement `APP_SECRET_ENCRYPTION_KEY`) fail the restore unless
  the operator asks for them to be cleared; clearing is audited and removes the value, never guesses it.
- Error text is redacted and never carries row content: `pg_restore` messages are reduced to their own
  `pg_restore:` lines, an unexpected exception is recorded by class name.
- Every instant is UTC.

Dependencies: SQLAlchemy and psycopg2 (database), boto3 (object store, injected), `pg_restore` 16, `restic` and
`age` binaries, `services.dr_backup`, `services.dr_manifest`, `services.dr_restic`, `services.dr_stats`,
`services.audit`.
"""

from __future__ import annotations

import getpass
import hashlib
import json
import shutil
import subprocess
import tarfile
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any

from sqlalchemy import String, cast, create_engine, inspect, select, text, update
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from app.database import Base
from app.models.encrypted_type import decrypts_with_current_key
from app.services.audit import log_event
from app.services.dr_backup import (
    AlreadyRunning,
    BackupConfig,
    BackupDeps,
    BackupError,
    deps_from_environment,
    pg_connection,
    require_password,
    run_lock,
    secret_values,
    sha256_file,
    write_atomic,
)
from app.services.dr_manifest import BackupManifest, ComponentKind, SecretsMode, load_manifest
from app.services.dr_restic import Redactor, Restic, ResticError
from app.services.dr_stats import collect_stats, compare_stats, encrypted_columns
from app.storage_backends.local import LocalFileStorageBackend

REPORT_FILENAME = "restore-report.json"
MAX_REPORTED_MISMATCHES = 100
"""Cap on statistics differences written to the report, so a wrong target does not produce a huge document."""

_DISK_MARGIN = 1.1
_DISK_FLOOR_BYTES = 64 * 1024 * 1024
_SWAP_ATTEMPTS = 3
_DEPENDENT_FLAGS: dict[tuple[str, str], tuple[str, ...]] = {("users", "totp_secret"): ("is_2fa_enabled",)}
"""Columns that must change with a cleared secret: a user whose TOTP secret is removed is no longer enrolled."""


class RestoreMode(str, Enum):
    """Where the set is going: an empty target (`fresh`) or one that holds data to replace (`in-place`)."""

    FRESH = "fresh"
    IN_PLACE = "in-place"


class RestoreError(RuntimeError):
    """A step failed or a guard refused; the message is redacted and safe for logs and the report.

    Attributes:
        step: The step that failed (`select`, `plan`, `download`, `checksums`, `objects`, `database`,
            `verify`, `secrets`, `swap`, `config`).
    """

    def __init__(self, step: str, message: str) -> None:
        super().__init__(message)
        self.step = step


@dataclass(frozen=True)
class SetInfo:
    """One backup set as the repository lists it.

    Attributes:
        snapshot_id: Full restic snapshot id.
        set_id: The set's sortable id (`20261024T020000Z`).
        time: The snapshot time as restic reports it.
        set_path: Absolute path of the set inside the snapshot.
        objects_path: Absolute path of the object mirror inside the snapshot, if the set has one.
        secrets_mode: `config` or `none` (`unknown` when the tag is missing).
    """

    snapshot_id: str
    set_id: str
    time: str
    set_path: str
    objects_path: str | None
    secrets_mode: str


@dataclass
class RestoreOptions:
    """What the operator asked for.

    Attributes:
        mode: Fresh or in-place.
        selector: `latest`, a set id, or a snapshot id prefix of at least 8 characters.
        repository: Repository to read instead of the configured primary (e.g. an off-site copy).
        dry_run: Plan and check only; change nothing.
        confirmed: The operator passed `--yes` (required to replace a live database).
        clear_unreadable_secrets: Remove encrypted values the configured key cannot decrypt instead of failing.
        maintenance_db: Database used for `CREATE`/`ALTER DATABASE` (not the one being restored).
        report_path: Where to always write the report (a dry run or a refusal included); None writes the status
            directory's `restore-report.json` only for a run that got far enough to change something, so a
            refused or dry run never replaces the record of the last real restore.
    """

    mode: RestoreMode
    selector: str = "latest"
    repository: str | None = None
    dry_run: bool = False
    confirmed: bool = False
    clear_unreadable_secrets: bool = False
    maintenance_db: str = "postgres"
    report_path: Path | None = None


@dataclass
class RestoreReport:
    """What a run did, as written to `restore-report.json` (step names, counts and ids only)."""

    result: str = "failed"
    mode: str = ""
    dry_run: bool = False
    set_id: str = ""
    snapshot_id: str = ""
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime | None = None
    step: str = "start"
    error: str | None = None
    plan: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    mismatches: list[dict[str, Any]] = field(default_factory=list)
    previous_database: str | None = None
    objects_restored: int = 0
    secrets_cleared: dict[str, int] = field(default_factory=dict)

    def to_json_dict(self) -> dict[str, Any]:
        """The report as JSON-ready data (instants as ISO 8601 with offset)."""
        data = asdict(self)
        data["started_at"] = self.started_at.isoformat()
        data["finished_at"] = self.finished_at.isoformat() if self.finished_at else None
        return data


@dataclass
class RestoreDeps:
    """What a run talks to, supplied by the caller so tests can substitute any of it.

    Attributes:
        db_url: URL of the database being restored into (the live name; the scratch database derives from it).
        restic: The restic wrapper.
        storage_backend: `s3` or `local`, the backend the target uses.
        storage_client: boto3 S3 client (s3 only).
        storage_bucket: Target bucket (s3 only).
        probe_storage: Backend the statistics probe checks file records against (None skips the probe).
        probe_encryption: Whether to try decrypting encrypted columns; false when no key was supplied.
        actor: Who is running it, for the audit record (`cli:<os user>`).
        now: Clock (UTC).
        sleep: Delay between swap retries.
    """

    db_url: str
    restic: Restic
    storage_backend: str
    storage_client: Any | None = None
    storage_bucket: str = ""
    probe_storage: Any | None = None
    probe_encryption: bool = True
    actor: str = "cli:unknown"
    now: Callable[[], datetime] = lambda: datetime.now(UTC)
    sleep: Callable[[float], None] = time.sleep


def restic_from_environment(config: BackupConfig) -> Restic:
    """Builds the restic wrapper alone (no database or object-store access), for `list` and `config`.

    Secrets named in the environment are redacted from anything it reports.
    """
    return Restic(
        config.password_file, redactor=Redactor(secret_values(None)), timeout=config.restic_timeout_seconds, no_lock=config.repository_read_only
    )


def restore_deps_from_environment(config: BackupConfig) -> RestoreDeps:
    """Builds the dependencies from the same environment the backend reads (`DATABASE_URL`, `STORAGE_*`).

    Args:
        config: Tool settings.

    Returns:
        Dependencies wired to the real database, object store and restic. Encrypted columns are only
        probed when `APP_SECRET_ENCRYPTION_KEY` was given to this process.
    """
    base: BackupDeps = deps_from_environment(config)
    probe = base.storage_for_probe if base.storage_backend == "s3" else LocalFileStorageBackend(str(config.local_files_dir))
    try:
        user = getpass.getuser()
    except (KeyError, OSError):  # an arbitrary container uid has no passwd entry
        user = "unknown"
    return RestoreDeps(
        db_url=base.db_url,
        restic=base.restic,
        storage_backend=base.storage_backend,
        storage_client=base.storage_client,
        storage_bucket=base.storage_bucket,
        probe_storage=probe,
        probe_encryption=base.probe_encryption,
        actor=f"cli:{user}",
    )


# --- sets ------------------------------------------------------------------------------------------------


def _tag(tags: list[str], prefix: str) -> str | None:
    return next((t[len(prefix) :] for t in tags if t.startswith(prefix)), None)


def list_sets(restic: Restic, repository: str) -> list[SetInfo]:
    """Lists the backup sets in a repository, newest first.

    Args:
        restic: The restic wrapper.
        repository: Repository to read.

    Returns:
        One entry per snapshot written by the backup tool (snapshots without a `set:` tag are ignored).

    Raises:
        ResticError: If the repository cannot be opened (unreachable, wrong password).
    """
    found: list[SetInfo] = []
    for record in restic.snapshots(repository):
        tags = record.get("tags") or []
        set_id = _tag(tags, "set:")
        paths = record.get("paths") or []
        set_path = next((p for p in paths if "/sets/" in p), None)
        if not set_id or not set_path:
            continue
        objects = next((p for p in paths if p.rstrip("/").endswith("/objects")), None)
        found.append(SetInfo(record["id"], set_id, record.get("time", ""), set_path, objects, _tag(tags, "secrets:") or "unknown"))
    return sorted(found, key=lambda info: info.set_id, reverse=True)


def resolve_set(sets: list[SetInfo], selector: str) -> SetInfo:
    """Picks one set.

    Args:
        sets: The repository's sets, newest first.
        selector: `latest`, a set id, or a snapshot id prefix of at least 8 characters.

    Raises:
        RestoreError: If the repository has no sets or the selector matches none or several.
    """
    if not sets:
        raise RestoreError("select", "the repository holds no backup sets")
    if selector == "latest":
        return sets[0]
    exact = [s for s in sets if s.set_id == selector]
    if exact:
        return exact[0]
    by_snapshot = [s for s in sets if len(selector) >= 8 and s.snapshot_id.startswith(selector)]
    if len(by_snapshot) == 1:
        return by_snapshot[0]
    if len(by_snapshot) > 1:
        raise RestoreError("select", "the snapshot prefix matches more than one set; use the set id")
    raise RestoreError("select", "no set matches the selector; run 'list' to see the sets available")


def read_manifest(restic: Restic, repository: str, info: SetInfo) -> BackupManifest:
    """Reads and validates a set's manifest straight from the repository (nothing else is downloaded).

    Raises:
        RestoreError: If the manifest is missing, unreadable, from a newer format, or names another set.
    """
    try:
        raw = restic.dump_file(repository, info.snapshot_id, f"{info.set_path}/manifest.json")
        manifest = load_manifest(raw.decode("utf-8"))
    except (ResticError, ValueError) as exc:  # pydantic's ValidationError is a ValueError
        raise RestoreError("select", f"cannot read the set's manifest: {exc}") from exc
    if manifest.set_id != info.set_id:
        raise RestoreError("select", "the manifest names a different set than its snapshot")
    return manifest


def describe_plan(info: SetInfo, manifest: BackupManifest) -> list[str]:
    """One line per fact an operator should see before agreeing to a restore (counts only)."""
    business = manifest.stats.business
    size = sum(c.bytes for c in manifest.components.values())
    app = manifest.app
    created = manifest.created_at.astimezone(UTC)
    lines = [
        f"set {info.set_id} (snapshot {info.snapshot_id[:8]}), taken {created:%Y-%m-%d %H:%M} UTC",
        f"app {app.version} ({app.git_sha[:8]}), image tag {app.image_tag or 'not recorded'}, schema {manifest.alembic_revision or 'none'}",
        f"postgres {manifest.postgres_version}, storage {manifest.storage_backend}, secrets mode {manifest.secrets_mode.value}, {size:,} bytes",
        (
            f"holds {business.organizations} organisations, {business.users.total} users, {business.projects} projects, "
            f"{sum(business.records.values())} records, {business.files.records} file records"
        ),
    ]
    if manifest.objects is not None:
        lines.append(f"object mirror: {manifest.objects.count} objects, {manifest.objects.bytes:,} bytes")
    return lines


# --- guards ----------------------------------------------------------------------------------------------


def code_revisions() -> tuple[set[str], set[str]]:
    """The Alembic revisions this image knows, as `(all revisions, heads)`, across core and module chains."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from app.modules.registry import configure_alembic_version_locations

    backend_dir = Path(__file__).resolve().parent.parent.parent
    cfg = Config(str(backend_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend_dir / "alembic"))
    configure_alembic_version_locations(cfg)
    script = ScriptDirectory.from_config(cfg)
    return {rev.revision for rev in script.walk_revisions()}, set(script.get_heads())


def compatibility_problems(
    manifest: BackupManifest, *, server_major: int, known_revisions: set[str], head_revisions: set[str], storage_backend: str
) -> list[str]:
    """Why this set cannot be restored into this target (empty means it can).

    Args:
        manifest: The set's manifest.
        server_major: Major version of the target PostgreSQL server.
        known_revisions: Every schema revision this image knows.
        head_revisions: The image's head revision(s).
        storage_backend: The target's file backend (`s3` or `local`).

    Returns:
        One sentence per problem; none contains row content or a secret.
    """
    problems: list[str] = []
    tag = manifest.app.image_tag or f"version {manifest.app.version}"
    revision = manifest.alembic_revision
    if revision is not None and revision not in known_revisions:
        problems.append(f"the set's schema revision {revision} is newer than this image knows; restore with the image it was taken with ({tag})")
    elif revision is not None and revision not in head_revisions:
        problems.append(
            f"the set's schema revision {revision} is older than this image's; verification needs the image it was taken with ({tag}). "
            "Restore with that image, then upgrade: the newer image migrates the database when it starts"
        )
    dump_major = int(manifest.postgres_version.split(".")[0])
    if server_major < dump_major:
        problems.append(
            f"the set was dumped from PostgreSQL {dump_major} and the target server is {server_major}; a dump does not restore into an older server"
        )
    if manifest.storage_backend != storage_backend:
        problems.append(
            f"the set's file records use the {manifest.storage_backend} backend but this target is STORAGE_BACKEND={storage_backend}; set it to match"
        )
    return problems


def required_disk_bytes(manifest: BackupManifest) -> int:
    """Free space needed to hold the fetched set (component sizes plus a margin)."""
    return int(sum(c.bytes for c in manifest.components.values()) * _DISK_MARGIN) + _DISK_FLOOR_BYTES


# --- database --------------------------------------------------------------------------------------------


def _engine(db_url: str, database: str | None = None, **options: Any) -> Engine:
    """An engine without a pool (a restore must not leave idle connections that block a rename)."""
    url = make_url(db_url)
    if database is not None:
        url = url.set(database=database)
    return create_engine(url, poolclass=NullPool, **options)


def _quote(engine: Engine, identifier: str) -> str:
    return engine.dialect.identifier_preparer.quote(identifier)


def database_has_data(db_url: str) -> bool:
    """Whether the target database holds any table in the `public` schema."""
    engine = _engine(db_url)
    try:
        with engine.connect() as conn:
            count = conn.execute(
                text("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public' AND table_type = 'BASE TABLE'")
            ).scalar_one()
    finally:
        engine.dispose()
    return count > 0


def server_major(db_url: str) -> int:
    """The target PostgreSQL server's major version."""
    engine = _engine(db_url)
    try:
        with engine.connect() as conn:
            return int(conn.execute(text("SHOW server_version_num")).scalar_one()) // 10000
    finally:
        engine.dispose()


def scratch_database_name(live: str, set_id: str) -> str:
    """The scratch database a set is restored into (`reqtrack_restore_20261024t020000z`, at most 63 characters)."""
    return f"{live}_restore_{set_id.lower()}"[:63]


def previous_database_name(live: str, now: datetime) -> str:
    """The name the replaced database is kept under (`reqtrack_pre_restore_20261024t030000z`)."""
    return f"{live}_pre_restore_{now.astimezone(UTC):%Y%m%dt%H%M%Sz}"[:63]


def restore_dump(config: BackupConfig, db_url: str, dump: Path, redact: Redactor) -> None:
    """Restores a custom-format dump into an empty database in one transaction.

    Raises:
        RestoreError: If `pg_restore` is missing or fails. Only its own `pg_restore:` lines are kept: the
            messages around them can quote the data that failed.
    """
    args, env = pg_connection(db_url)
    argv = [config.pg_restore, "--single-transaction", "--exit-on-error", "--no-owner", "--no-privileges", "--no-password", *args, str(dump)]
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, env=env, check=False)
    except OSError as exc:
        raise RestoreError("database", redact(f"cannot run pg_restore: {exc}")) from exc
    if proc.returncode != 0:
        lines = [line[:200] for line in (proc.stderr or "").splitlines() if line.startswith("pg_restore:")]
        raise RestoreError("database", redact(f"pg_restore failed (exit {proc.returncode}): {' | '.join(lines[:2])}"))


def swap_databases(admin: Engine, *, live: str, new: str, keep_old_as: str | None, sleep: Callable[[float], None]) -> None:
    """Replaces the live database with the restored one by renaming.

    Args:
        admin: An autocommit engine on a maintenance database (not `live` or `new`).
        live: The database the application uses.
        new: The verified scratch database.
        keep_old_as: Name to keep the replaced database under; None drops it (a verified-empty fresh target).
        sleep: Delay between attempts.

    Raises:
        RestoreError: If other sessions keep reconnecting to `live`, or a rename fails. If the second rename
            fails after the first succeeded, the first is undone so the application's database name is not
            left empty.
    """
    last: Exception | None = None
    for attempt in range(_SWAP_ATTEMPTS):
        if attempt:
            sleep(1.0)
        try:
            with admin.connect() as conn:
                conn.execute(
                    text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname IN (:live, :new) AND pid <> pg_backend_pid()"),
                    {"live": live, "new": new},
                )
                if keep_old_as is None:
                    conn.execute(text(f"DROP DATABASE {_quote(admin, live)}"))
                else:
                    conn.execute(text(f"ALTER DATABASE {_quote(admin, live)} RENAME TO {_quote(admin, keep_old_as)}"))
                try:
                    conn.execute(text(f"ALTER DATABASE {_quote(admin, new)} RENAME TO {_quote(admin, live)}"))
                except SQLAlchemyError:
                    if keep_old_as is not None:
                        conn.execute(text(f"ALTER DATABASE {_quote(admin, keep_old_as)} RENAME TO {_quote(admin, live)}"))
                    raise
            return
        except SQLAlchemyError as exc:
            last = exc
    raise RestoreError(
        "swap",
        f"could not swap the restored database into place after {_SWAP_ATTEMPTS} attempts ({type(last).__name__}); the live database is unchanged",
    )


def clear_unreadable_secrets(engine: Engine, *, set_id: str, actor: str) -> dict[str, int]:
    """Removes encrypted values the configured key cannot decrypt, and records that it did.

    A user whose TOTP secret is removed is also marked not enrolled for 2FA. Everything runs in one
    transaction with one audit event (counts per column only).

    Args:
        engine: Engine on the database to change.
        set_id: The set being restored (the audit event's subject).
        actor: Who ran it (`cli:<os user>`).

    Returns:
        `{"table.column": values cleared}` for the columns that had any.

    Raises:
        RestoreError: If an encrypted column's table has no single-column primary key.
    """
    cleared: dict[str, int] = {}
    present = set(inspect(engine).get_table_names())
    with Session(engine) as db:
        for table_name, column_name in encrypted_columns():
            if table_name not in present:
                continue
            table = Base.metadata.tables[table_name]
            keys = list(table.primary_key.columns)
            if len(keys) != 1:
                raise RestoreError("secrets", f"cannot clear {table_name}.{column_name}: no single-column primary key")
            column = table.c[column_name]
            rows = db.execute(select(keys[0], cast(column, String)).where(column.is_not(None))).all()
            unreadable = [row_id for row_id, value in rows if not decrypts_with_current_key(value)]
            if not unreadable:
                continue
            values: dict[str, Any] = {column_name: None}
            values.update({flag: False for flag in _DEPENDENT_FLAGS.get((table_name, column_name), ())})
            db.execute(update(table).where(keys[0].in_(unreadable)).values(**values))
            cleared[f"{table_name}.{column_name}"] = len(unreadable)
        if cleared:
            log_event(
                db,
                entity_type="restore",
                entity_id=set_id,
                action="secrets_cleared",
                actor_id=None,
                detail={"actor": actor, "columns": cleared},
            )
        db.commit()
    return cleared


# --- files -----------------------------------------------------------------------------------------------


def verify_components(manifest: BackupManifest, set_dir: Path, objects_dir: Path | None) -> None:
    """Checks the fetched set against the manifest's digests before anything is changed.

    Args:
        manifest: The set's manifest.
        set_dir: The fetched set directory.
        objects_dir: The fetched object mirror, if the set has one.

    Raises:
        RestoreError: If a file is missing or its SHA-256 differs, or the mirror holds fewer objects than the manifest records.
    """
    for kind, entry in manifest.components.items():
        if kind is ComponentKind.OBJECTS:
            continue
        path = set_dir / entry.path
        if not path.is_file():
            raise RestoreError("checksums", f"the {kind.value} component is missing from the fetched set")
        digest, _ = sha256_file(path)
        if digest != entry.sha256:
            raise RestoreError("checksums", f"the {kind.value} component does not match the manifest's checksum")
    if manifest.objects is not None:
        count = sum(1 for p in objects_dir.rglob("*") if p.is_file()) if objects_dir and objects_dir.is_dir() else 0
        if count < manifest.objects.count:
            raise RestoreError("checksums", f"the object mirror holds {count} objects but the manifest records {manifest.objects.count}")


def upload_objects(client: Any, bucket: str, root: Path) -> int:
    """Puts every mirrored object into the bucket under its original key, creating the bucket if needed.

    Objects are only added or overwritten with identical content, never deleted, so rerunning is safe.

    Args:
        client: A boto3 S3 client.
        bucket: Target bucket.
        root: The fetched object mirror.

    Returns:
        The number of objects uploaded.

    Raises:
        RestoreError: If a size check after upload fails or the store refuses a request. Errors name an
            object only by position, never by key (storage keys are Confidential).
    """
    try:
        client.head_bucket(Bucket=bucket)
    except Exception:  # noqa: BLE001  (the application creates the bucket on any head failure too)
        try:
            client.create_bucket(Bucket=bucket)
        except Exception as exc:  # noqa: BLE001
            raise RestoreError("objects", f"cannot create the bucket ({type(exc).__name__})") from exc
    count = 0
    for path in sorted(p for p in root.rglob("*") if p.is_file() or p.is_symlink()):
        if path.is_symlink():
            raise RestoreError("objects", "the object mirror contains a symbolic link")
        key = path.relative_to(root).as_posix()
        size = path.stat().st_size
        try:
            with path.open("rb") as body:
                client.put_object(Bucket=bucket, Key=key, Body=body, ContentLength=size)
            stored = int(client.head_object(Bucket=bucket, Key=key)["ContentLength"])
        except Exception as exc:  # noqa: BLE001  (boto raises many types)
            raise RestoreError("objects", f"uploading object {count + 1} failed ({type(exc).__name__})") from exc
        if stored != size:
            raise RestoreError("objects", f"object {count + 1} was stored with the wrong size")
        count += 1
    return count


def extract_local_files(archive: Path, destination: Path) -> int:
    """Unpacks the local file store archive (`files/...`) into `destination`.

    Only regular files and directories under `files/` are accepted; a link, device, absolute or traversing
    member fails the restore rather than being skipped.

    Returns:
        The number of files written.

    Raises:
        RestoreError: On an unsafe member.
    """
    written = 0
    destination.mkdir(parents=True, exist_ok=True)
    root = destination.resolve()
    with tarfile.open(archive, "r") as tar:
        for member in tar:
            parts = member.name.split("/")
            if parts[0] != "files" or ".." in parts or member.name.startswith("/"):
                raise RestoreError("objects", "the local files archive contains a member outside files/")
            relative = parts[1:]
            if not relative or relative == [""]:
                continue
            target = root.joinpath(*relative)
            if root not in target.resolve().parents:
                raise RestoreError("objects", "the local files archive contains a path that escapes the store")
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            elif member.isreg():
                target.parent.mkdir(parents=True, exist_ok=True)
                source = tar.extractfile(member)
                if source is None:
                    raise RestoreError("objects", "the local files archive has an unreadable member")
                with source, target.open("wb") as out:
                    shutil.copyfileobj(source, out)
                written += 1
            else:
                raise RestoreError("objects", "the local files archive contains a link or special file")
    return written


# --- config ----------------------------------------------------------------------------------------------


def decrypt_config(config: BackupConfig, restic: Restic, repository: str, selector: str, identity: Path) -> bytes:
    """Decrypts a set's age-encrypted `.env` snapshot, for provisioning a fresh host.

    Args:
        config: Tool settings (password file).
        restic: The restic wrapper.
        repository: Repository to read.
        selector: Which set (`latest`, a set id or snapshot prefix).
        identity: File holding the age identity (private key) the `.env` was encrypted to.

    Returns:
        The plaintext `.env`. The caller decides where it goes; it is never logged.

    Raises:
        RestoreError: If the set holds no configuration (`none` mode), the checksum differs, or `age` cannot decrypt it.
    """
    require_password(config.password_file)
    info = resolve_set(list_sets(restic, repository), selector)
    manifest = read_manifest(restic, repository, info)
    entry = manifest.components.get(ComponentKind.CONFIG)
    if manifest.secrets_mode is SecretsMode.NONE or entry is None:
        raise RestoreError("config", "this set holds no configuration snapshot (it was taken with BACKUP_SECRETS_MODE=none); supply your own .env")
    try:
        encrypted = restic.dump_file(repository, info.snapshot_id, f"{info.set_path}/{entry.path}")
    except ResticError as exc:
        raise RestoreError("config", f"cannot read the configuration snapshot: {exc}") from exc
    if hashlib.sha256(encrypted).hexdigest() != entry.sha256:
        raise RestoreError("config", "the configuration snapshot does not match the manifest's checksum")
    try:
        proc = subprocess.run(["age", "--decrypt", "--identity", str(identity)], input=encrypted, capture_output=True, check=False)
    except OSError as exc:
        raise RestoreError("config", restic.redact(f"cannot run age: {exc}")) from exc
    if proc.returncode != 0:
        raise RestoreError(
            "config", f"age could not decrypt the configuration (wrong identity?): {proc.stderr.decode('utf-8', 'replace').strip()[:200]}"
        )
    return proc.stdout


# --- the run ---------------------------------------------------------------------------------------------


def run_restore(config: BackupConfig, deps: RestoreDeps, options: RestoreOptions) -> RestoreReport:
    """Runs one restore (or its dry run) end to end.

    Args:
        config: Tool settings.
        deps: The database, object store, restic wrapper and clock to use.
        options: What the operator asked for.

    Returns:
        The report (written per `RestoreOptions.report_path`, and to `restore-report.json` in the status directory
        when the run got past planning). Failures never raise: they are recorded with `result == "failed"`. A
        dry run ends with `result == "dry-run"` and changes nothing.

    Raises:
        AlreadyRunning: If a backup or another restore holds the lock (nothing is written).
    """
    redact = deps.restic.redact
    report = RestoreReport(mode=options.mode.value, dry_run=options.dry_run, started_at=deps.now())
    refused = False
    try:
        _restore(config, deps, options, report)
    except AlreadyRunning:
        refused = True
        raise
    except RestoreError as exc:
        report.step, report.error = exc.step, str(exc)
    except (BackupError, ResticError, OSError) as exc:
        report.error = redact(str(exc))
    except SQLAlchemyError as exc:
        report.error = f"database error ({type(exc).__name__})"
    except Exception as exc:  # last resort: the class only, the message may carry data
        report.error = f"unexpected {type(exc).__name__}"
    finally:
        report.finished_at = deps.now()
        if not refused:
            changed_something = not options.dry_run and report.step not in {"start", "select", "plan"}
            targets = [options.report_path] if options.report_path else []
            if changed_something:
                targets.append(config.status_dir / REPORT_FILENAME)
            for target in targets:
                try:
                    write_atomic(target, _dump(report))
                except OSError:  # a report that cannot be written must not hide the outcome
                    report.warnings.append("the report could not be written")
    return report


def _dump(report: RestoreReport) -> str:
    """The report as the JSON text written to `restore-report.json`."""
    return json.dumps(report.to_json_dict(), indent=2) + "\n"


def _restore(config: BackupConfig, deps: RestoreDeps, options: RestoreOptions, report: RestoreReport) -> None:
    """The ordered steps of a run; raises on the first failure, with `report.step` naming the step reached."""
    redact, restic = deps.restic.redact, deps.restic
    repository = options.repository or config.repository

    report.step = "select"
    require_password(config.password_file)
    info = resolve_set(list_sets(restic, repository), options.selector)
    report.set_id, report.snapshot_id = info.set_id, info.snapshot_id
    manifest = read_manifest(restic, repository, info)
    report.plan = describe_plan(info, manifest)

    report.step = "plan"
    known, heads = code_revisions()
    problems = compatibility_problems(
        manifest, server_major=server_major(deps.db_url), known_revisions=known, head_revisions=heads, storage_backend=deps.storage_backend
    )
    has_data = database_has_data(deps.db_url)
    if options.mode is RestoreMode.FRESH and has_data:
        problems.append("the target database already holds data; a fresh restore needs an empty one (use in-place to replace a live database)")
    if problems:
        raise RestoreError("plan", "; ".join(problems))
    if manifest.secrets_mode is SecretsMode.NONE:
        report.warnings.append(
            "the set holds no configuration snapshot: the target must already have the original APP_SECRET_ENCRYPTION_KEY and JWT_SECRET"
        )
    if not deps.probe_encryption:
        report.warnings.append("APP_SECRET_ENCRYPTION_KEY was not supplied: encrypted columns were not checked")
    if options.clear_unreadable_secrets and not deps.probe_encryption:
        raise RestoreError(
            "plan", "--clear-unreadable-secrets needs the key the application will use (a new APP_SECRET_ENCRYPTION_KEY if the original is lost)"
        )
    if options.dry_run:
        report.result, report.step = "dry-run", "done"
        return
    if options.mode is RestoreMode.IN_PLACE and not options.confirmed:
        raise RestoreError("plan", "an in-place restore replaces the live database; pass --yes to confirm")

    with run_lock(config.staging_dir):
        scratch = config.staging_dir / f"restore-{info.set_id}"
        if scratch.exists():
            shutil.rmtree(scratch)
        scratch.mkdir(parents=True, mode=0o700)
        scratch_db: str | None = None
        admin = _engine(deps.db_url, options.maintenance_db, isolation_level="AUTOCOMMIT")
        try:
            report.step = "download"
            free = shutil.disk_usage(config.staging_dir).free
            if free < required_disk_bytes(manifest):
                raise RestoreError(
                    "download", f"not enough free space in the staging area: {free:,} bytes free, about {required_disk_bytes(manifest):,} needed"
                )
            restic.restore(repository, info.snapshot_id, scratch, verify=True)
            set_dir = scratch / info.set_path.lstrip("/")
            objects_dir = scratch / info.objects_path.lstrip("/") if info.objects_path else None

            report.step = "checksums"
            verify_components(manifest, set_dir, objects_dir)

            report.step = "objects"
            if manifest.storage_backend == "s3":
                if deps.storage_client is None:
                    raise RestoreError("objects", "STORAGE_BACKEND=s3 but no object-store client is available")
                if objects_dir is not None and objects_dir.is_dir():
                    report.objects_restored = upload_objects(deps.storage_client, deps.storage_bucket, objects_dir)
            elif ComponentKind.LOCAL_FILES in manifest.components:
                report.objects_restored = extract_local_files(set_dir / manifest.components[ComponentKind.LOCAL_FILES].path, config.local_files_dir)

            report.step = "database"
            live = make_url(deps.db_url).database or ""
            scratch_db = scratch_database_name(live, info.set_id)
            with admin.connect() as conn:
                conn.execute(text(f"DROP DATABASE IF EXISTS {_quote(admin, scratch_db)}"))
                conn.execute(text(f"CREATE DATABASE {_quote(admin, scratch_db)}"))
            scratch_url = make_url(deps.db_url).set(database=scratch_db).render_as_string(hide_password=False)
            restore_dump(config, scratch_url, set_dir / manifest.components[ComponentKind.DATABASE].path, redact)

            report.step = "verify"
            unreadable = _verify(scratch_url, manifest, deps, options, report)

            if unreadable:
                report.step = "secrets"
                scratch_engine = _engine(scratch_url)
                try:
                    report.secrets_cleared = clear_unreadable_secrets(scratch_engine, set_id=info.set_id, actor=deps.actor)
                finally:
                    scratch_engine.dispose()

            report.step = "swap"
            keep_old = previous_database_name(live, deps.now()) if has_data else None
            swap_databases(admin, live=live, new=scratch_db, keep_old_as=keep_old, sleep=deps.sleep)
            scratch_db = None
            report.previous_database = keep_old
            report.result, report.step = "ok", "done"
        finally:
            if scratch_db is not None:
                try:
                    with admin.connect() as conn:
                        conn.execute(text(f"DROP DATABASE IF EXISTS {_quote(admin, scratch_db)} WITH (FORCE)"))
                except SQLAlchemyError:
                    report.warnings.append(f"the scratch database {scratch_db} could not be removed; drop it by hand")
            admin.dispose()
            shutil.rmtree(scratch, ignore_errors=True)


def _verify(scratch_url: str, manifest: BackupManifest, deps: RestoreDeps, options: RestoreOptions, report: RestoreReport) -> dict[str, int]:
    """Recomputes the statistics on the restored scratch database and holds them to the manifest.

    Args:
        scratch_url: URL of the restored scratch database.
        manifest: The set's manifest.
        deps: Run dependencies (storage probe, whether to probe encryption).
        options: Whether unreadable secrets may be cleared rather than failing.
        report: Receives the mismatches and warnings.

    Returns:
        The encrypted columns holding values the key cannot read, as `{"table.column": count}`; non-empty only
        when the operator allowed clearing them.

    Raises:
        RestoreError: On a statistics difference, a file record with no object, or (unless clearing is allowed)
            an encrypted value the configured key cannot read.
    """
    engine = _engine(scratch_url)
    try:
        with Session(engine) as db:
            actual = collect_stats(db, deps.probe_storage, probe_encryption=deps.probe_encryption)
            db.rollback()
    finally:
        engine.dispose()
    try:
        mismatches = compare_stats(manifest.stats, actual)
    except ValueError as exc:
        raise RestoreError("verify", str(exc)) from exc
    if mismatches:
        report.mismatches = [m.model_dump() for m in mismatches[:MAX_REPORTED_MISMATCHES]]
        first = mismatches[0]
        raise RestoreError(
            "verify", f"{len(mismatches)} statistics differ from the manifest (first: {first.path} expected {first.expected!r}, got {first.actual!r})"
        )
    files = actual.probes.files
    if files.missing:
        raise RestoreError("verify", f"{files.missing} of {files.checked} file records have no stored object after the restore")
    unreadable = {column: probe.undecryptable for column, probe in actual.probes.encrypted_columns.items() if probe.undecryptable}
    if unreadable and not options.clear_unreadable_secrets:
        detail = ", ".join(f"{column} ({count})" for column, count in sorted(unreadable.items()))
        raise RestoreError(
            "verify",
            f"the configured APP_SECRET_ENCRYPTION_KEY cannot decrypt: {detail}. Supply the original key, or run again with "
            "--clear-unreadable-secrets to remove those values (users with 2FA re-enrol; organisation SMTP and SSO secrets are re-entered)",
        )
    if unreadable:
        report.warnings.append(
            "unreadable encrypted values will be cleared: " + ", ".join(f"{column} ({count})" for column, count in sorted(unreadable.items()))
        )
    return unreadable
