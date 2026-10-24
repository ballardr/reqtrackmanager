"""
Module: services.dr_backup

The backup run: one command that produces a self-describing, encrypted, verified backup set, copies it to
every configured destination and applies retention.

Responsibilities:
- Read the tool's configuration (`BackupConfig`, `BACKUP_*` environment variables).
- Take the database dump and the statistics in one Postgres snapshot, then mirror the object store
  (dump first, so every dumped row finds its object), archive local files when that backend is in use, and
  optionally encrypt the operator's `.env` to an age recipient.
- Write the manifest, store the set as a restic snapshot, copy it to each destination, prune, and run a
  sampled integrity check.
- Refuse a concurrent run, and always leave a `status.json` and a Prometheus textfile saying what happened.

Design decisions:
- A run is all-or-nothing for the primary repository: any failure before the snapshot exists aborts with a
  non-zero exit. A destination that fails after the snapshot exists is recorded per destination and still
  fails the run's exit status: an off-site copy that silently did not happen is the failure to avoid.
- The staged set (which holds an unencrypted dump) is removed whether the run succeeds or fails.
- `BACKUP_SECRETS_MODE=none` never reads the operator's `.env`; `config` mode refuses to run without a
  readable one and an age recipient, so a set is never silently missing the key it advertises.
- `status.json` and the metrics file never contain a secret, a key, a row value or a storage key; errors
  are redacted before they are stored.
- Every instant is UTC.

Dependencies: SQLAlchemy and psycopg2 (database), boto3 (object store), `pg_dump` 16, `restic` and `age`
binaries, `services.dr_stats`, `services.dr_manifest`, `services.dr_restic`, `services.dr_object_mirror`.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session

from app.services.dr_manifest import (
    MANIFEST_FILENAME,
    AppIdentity,
    BackupManifest,
    ComponentEntry,
    ComponentKind,
    ObjectsSummary,
    SecretsMode,
    dump_manifest,
)
from app.services.dr_object_mirror import ObjectMirror
from app.services.dr_restic import Redactor, Restic, ResticError, Retention
from app.services.dr_stats import DrStats, collect_stats, probe_failures

TOOL_VERSION = "1.0.0"
SNAPSHOT_HOST = "reqtrack-backup"
"""Fixed restic host so retention groups every set together whichever container ran it."""

EX_TEMPFAIL = 75
"""Exit status for a refused concurrent run (sysexits `EX_TEMPFAIL`)."""

_SET_ID_FORMAT = "%Y%m%dT%H%M%SZ"
_SECRET_NAME = re.compile(r"KEY|SECRET|PASSWORD|TOKEN|CREDENTIAL", re.I)
"""Names of `.env` entries whose values are masked; masking every value would hide hosts and paths in errors."""
_ENV_SECRET_KEYS = {"APP_SECRET_ENCRYPTION_KEY", "JWT_SECRET", "POSTGRES_PASSWORD", "STORAGE_SECRET_KEY", "SMTP_PASSWORD", "SERVER_ADMIN_PASSWORD"}


class BackupError(RuntimeError):
    """A step failed; the message is redacted and safe for logs and `status.json`.

    Attributes:
        step: The step that failed (`dump`, `stats`, `mirror`, `config`, `snapshot`, `copy`, `retention`, `check`).
    """

    def __init__(self, step: str, message: str) -> None:
        super().__init__(message)
        self.step = step


class AlreadyRunning(RuntimeError):
    """Another backup holds the lock."""


class BackupConfig(BaseSettings):
    """Backup tool settings, read from `BACKUP_*` environment variables.

    Attributes:
        staging_dir: Working area; holds the persistent object mirror and the transient set.
        repository: Primary restic repository (path or URL).
        password_file: File with the repository password (a Docker secret).
        destinations_raw: Comma- or newline-separated extra restic repositories each snapshot is copied to.
        secrets_mode: `config` also stores an age-encrypted `.env`; `none` stores no key material.
        env_file: The operator's `.env`, mounted read-only (config mode only).
        config_age_recipient: age public key the `.env` is encrypted to (its identity is kept elsewhere).
        keep_hourly / keep_daily / keep_weekly / keep_monthly: Retention policy (restic keeps the latest set of each
            period, so a schedule more often than daily needs `keep_hourly` to retain the extra sets).
        check_subset: Share of repository data read by the integrity check (`5%`; empty to skip).
        status_dir: Where `status.json` and `reqtrack-backup.prom` are written.
        local_files_dir: The local file store, archived when `STORAGE_BACKEND=local`.
        pg_dump: The `pg_dump` executable (must be the server's major version or newer, within reason).
        restic_timeout_seconds: Longest one restic command may run before the step fails.
    """

    model_config = SettingsConfigDict(env_prefix="BACKUP_", extra="ignore", populate_by_name=True)

    staging_dir: Path = Path("/backup/staging")
    repository: str = "/backup/repo"
    password_file: Path = Path("/run/secrets/backup_repo_password")
    destinations_raw: str = Field(default="", alias="BACKUP_DESTINATIONS")
    secrets_mode: SecretsMode = SecretsMode.CONFIG
    env_file: Path = Path("/run/backup/env")
    config_age_recipient: str = ""
    keep_hourly: int = Field(default=0, ge=0)
    keep_daily: int = Field(default=7, ge=0)
    keep_weekly: int = Field(default=4, ge=0)
    keep_monthly: int = Field(default=12, ge=0)
    check_subset: str = "5%"
    status_dir: Path = Path("/backup/status")
    local_files_dir: Path = Path("/source/local_files")
    pg_dump: str = "pg_dump"
    restic_timeout_seconds: float = Field(default=4 * 3600, gt=0)

    @field_validator("check_subset")
    @classmethod
    def _subset(cls, value: str) -> str:
        """Accepts empty (skip) or restic's `n%` / `n/m` forms only, never an arbitrary option string."""
        if value and not all(c.isdigit() or c in "%/." for c in value):
            raise ValueError("BACKUP_CHECK_SUBSET must look like 5% or 1/10")
        return value

    @property
    def destinations(self) -> list[str]:
        """The extra repositories, with blanks removed."""
        return [d.strip() for d in self.destinations_raw.replace("\n", ",").split(",") if d.strip()]

    @property
    def retention(self) -> Retention:
        """The retention policy as the restic wrapper takes it."""
        return Retention(self.keep_hourly, self.keep_daily, self.keep_weekly, self.keep_monthly)


@dataclass
class DestinationResult:
    """The outcome of copying and pruning one destination (`target` is already redacted)."""

    target: str
    ok: bool
    error: str | None = None


@dataclass
class RunReport:
    """What a run did, as written to `status.json`."""

    result: str = "failed"
    set_id: str = ""
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime | None = None
    step: str = "start"
    error: str | None = None
    snapshot_id: str | None = None
    set_bytes: int = 0
    bytes_added: int = 0
    secrets_mode: str = ""
    destinations: list[DestinationResult] = field(default_factory=list)


def new_set_id(now: datetime) -> str:
    """The sortable id of a set started at `now` (UTC)."""
    return now.astimezone(UTC).strftime(_SET_ID_FORMAT)


@contextmanager
def run_lock(staging_dir: Path) -> Iterator[None]:
    """Holds an exclusive lock for the duration of a run.

    Raises:
        AlreadyRunning: If another process holds it.
    """
    staging_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    handle = open(staging_dir / ".backup.lock", "w")  # noqa: SIM115  (held for the context's lifetime)
    try:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise AlreadyRunning("another backup is already running") from exc
        yield
    finally:
        handle.close()


def _sha256_file(path: Path) -> tuple[str, int]:
    """Returns the SHA-256 and size of a file, read in blocks."""
    digest, size = hashlib.sha256(), 0
    with path.open("rb") as handle:
        while block := handle.read(1024 * 1024):
            digest.update(block)
            size += len(block)
    return digest.hexdigest(), size


def require_password(password_file: Path) -> None:
    """Refuses a missing or empty repository password file (an empty password would encrypt with nothing).

    Raises:
        BackupError: If the file is absent or empty.
    """
    if not password_file.is_file() or password_file.stat().st_size == 0:
        raise BackupError("config", "the repository password file (BACKUP_PASSWORD_FILE) is missing or empty")


def _entry(path: Path, set_dir: Path) -> ComponentEntry:
    sha, size = _sha256_file(path)
    return ComponentEntry(path=path.relative_to(set_dir).as_posix(), sha256=sha, bytes=size)


def _pg_env(db_url: str) -> tuple[list[str], dict[str, str]]:
    """Splits a database URL into `pg_dump` connection arguments and an environment holding the password.

    The password is passed through `PGPASSWORD`, never on the command line.
    """
    url = make_url(db_url)
    args = ["--host", url.host or "localhost", "--port", str(url.port or 5432), "--username", url.username or "", "--dbname", url.database or ""]
    env = dict(os.environ)
    if url.password:
        env["PGPASSWORD"] = url.password
    return args, env


def dump_database(config: BackupConfig, db_url: str, snapshot_id: str, out: Path, redact: Redactor) -> None:
    """Runs `pg_dump` (custom format) against an exported snapshot.

    Raises:
        BackupError: If `pg_dump` is missing or exits non-zero.
    """
    args, env = _pg_env(db_url)
    argv = [config.pg_dump, "--format=custom", "--no-password", f"--snapshot={snapshot_id}", f"--file={out}", *args]
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, env=env, check=False)
    except OSError as exc:
        raise BackupError("dump", redact(f"cannot run pg_dump: {exc}")) from exc
    if proc.returncode != 0:
        tail = " | ".join((proc.stderr or "").strip().splitlines()[-3:])
        raise BackupError("dump", redact(f"pg_dump failed (exit {proc.returncode}): {tail}"))
    out.chmod(0o600)


def archive_local_files(source: Path, out: Path) -> None:
    """Writes the local file store as an uncompressed tar (restic compresses and deduplicates).

    Raises:
        BackupError: If `source` does not exist.
    """
    if not source.is_dir():
        raise BackupError("local_files", "STORAGE_BACKEND=local but the local file store is not mounted into the backup container")
    with tarfile.open(out, "w") as archive:
        archive.add(source, arcname="files")
    out.chmod(0o600)


def encrypt_config(env_file: Path, recipient: str, out: Path, redact: Redactor) -> None:
    """Encrypts the operator's `.env` to an age recipient (public key), so the backup host cannot read it back.

    Raises:
        BackupError: If the file is missing or empty, no recipient is set, or `age` fails.
    """
    if not recipient:
        raise BackupError("config", "BACKUP_SECRETS_MODE=config needs BACKUP_CONFIG_AGE_RECIPIENT (an age public key)")
    if not env_file.is_file() or env_file.stat().st_size == 0:
        raise BackupError("config", "BACKUP_SECRETS_MODE=config needs the .env mounted at BACKUP_ENV_FILE (or set BACKUP_SECRETS_MODE=none)")
    try:
        proc = subprocess.run(["age", "--recipient", recipient, "--output", str(out), str(env_file)], capture_output=True, text=True, check=False)
    except OSError as exc:
        raise BackupError("config", redact(f"cannot run age: {exc}")) from exc
    if proc.returncode != 0:
        raise BackupError("config", redact(f"age failed: {(proc.stderr or '').strip()[:200]}"))
    out.chmod(0o600)


def secret_values(env_file: Path | None) -> list[str]:
    """Collects the secret values to redact: well-known variables and, in config mode, the `.env` entries named like secrets."""
    values = [os.environ.get(k, "") for k in _ENV_SECRET_KEYS]
    values += [os.environ.get(k, "") for k in ("STORAGE_S3_SECRET_KEY", "AWS_SECRET_ACCESS_KEY", "AZURE_ACCOUNT_KEY", "PGPASSWORD")]
    try:
        values.append(make_url(os.environ.get("DATABASE_URL", "")).password or "")
    except Exception:  # an unparseable URL has nothing to redact
        pass
    if env_file is not None and env_file.is_file():
        for line in env_file.read_text(errors="replace").splitlines():
            name, sep, value = line.partition("=")
            if sep and not name.lstrip().startswith("#") and _SECRET_NAME.search(name):
                values.append(value.strip().strip("'\""))
    return values


@dataclass
class BackupDeps:
    """What a run reads from and writes to, supplied by the caller so tests can substitute any of it.

    Attributes:
        engine: SQLAlchemy engine for the database being backed up.
        db_url: Connection URL handed to `pg_dump`.
        storage_backend: `s3` or `local`, the backend file records point at.
        storage_client: boto3 S3 client (s3 backend only).
        storage_bucket: The bucket mirrored (s3 backend only).
        storage_for_probe: The `FileStorageBackend` the statistics probe file records against (None skips it).
        restic: The restic wrapper.
        dumper: Produces the dump file.
        now: Clock (UTC).
        probe_encryption: Whether to try decrypting encrypted columns; false when the tool was not given the key.
    """

    engine: Engine
    db_url: str
    storage_backend: str
    restic: Restic
    storage_client: Any | None = None
    storage_bucket: str = ""
    storage_for_probe: Any | None = None
    dumper: Callable[[BackupConfig, str, str, Path, Redactor], None] = dump_database
    now: Callable[[], datetime] = lambda: datetime.now(UTC)
    probe_encryption: bool = True


def deps_from_environment(config: BackupConfig) -> BackupDeps:
    """Builds the dependencies from the same environment the backend reads (`DATABASE_URL`, `STORAGE_*`).

    Args:
        config: Tool settings.

    Returns:
        Dependencies wired to the real database, object store and restic. Encrypted columns are only probed
        when `APP_SECRET_ENCRYPTION_KEY` was given to this process (a `none`-mode deployment may keep it out).
    """
    import boto3
    from botocore.client import Config

    from app.config import get_settings
    from app.database import engine
    from app.services.files import get_storage_backend

    settings = get_settings()
    redact = Redactor(secret_values(config.env_file if config.secrets_mode is SecretsMode.CONFIG else None))
    client = None
    if settings.storage_backend == "s3":
        client = boto3.client(
            "s3",
            endpoint_url=settings.storage_s3_endpoint_url,
            aws_access_key_id=settings.storage_s3_access_key,
            aws_secret_access_key=settings.storage_s3_secret_key,
            region_name=settings.storage_s3_region,
            config=Config(signature_version="s3v4"),
        )
    return BackupDeps(
        engine=engine,
        db_url=settings.database_url,
        storage_backend=settings.storage_backend,
        restic=Restic(config.password_file, redactor=redact, timeout=config.restic_timeout_seconds),
        storage_client=client,
        storage_bucket=settings.storage_s3_bucket,
        storage_for_probe=get_storage_backend(),
        probe_encryption=bool(os.environ.get("APP_SECRET_ENCRYPTION_KEY")),
    )


def write_bundle(config: BackupConfig, restic: Restic, recipient: str, output: Path) -> None:
    """Writes the latest set as one age-encrypted tar, for copying by hand (scp, a USB disk).

    The bundle is the whole restored snapshot (dump, manifest, object mirror, and the already age-encrypted
    `.env` snapshot when the set has one), encrypted to `recipient`; whoever holds the matching identity can
    unpack it without restic.

    Args:
        config: Tool settings (the primary repository).
        restic: The restic wrapper.
        recipient: age public key to encrypt to.
        output: Destination file (written with mode 0600).

    Raises:
        BackupError: If there is no recipient or no snapshot, or `age` fails.
    """
    require_password(config.password_file)
    if not recipient:
        raise BackupError("bundle", "a bundle needs an age recipient (BACKUP_BUNDLE_AGE_RECIPIENT or --recipient)")
    if not restic.snapshots(config.repository):
        raise BackupError("bundle", "the repository holds no snapshot to bundle")
    config.staging_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.TemporaryDirectory(dir=config.staging_dir, prefix="bundle-") as scratch:
        root = Path(scratch)
        restic.restore(config.repository, "latest", root / "restored")
        tar_path = root / "bundle.tar"
        with tarfile.open(tar_path, "w") as archive:
            archive.add(root / "restored", arcname="reqtrack-backup")
        proc = subprocess.run(["age", "--recipient", recipient, "--output", str(output), str(tar_path)], capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise BackupError("bundle", restic.redact(f"age failed: {(proc.stderr or '').strip()[:200]}"))
    output.chmod(0o600)


def _write_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}-")
    with os.fdopen(fd, "w") as handle:
        handle.write(content)
    os.chmod(tmp, 0o644)
    os.replace(tmp, path)


def write_status(status_dir: Path, report: RunReport, previous_success: float | None) -> None:
    """Writes `status.json` and the Prometheus textfile for a finished run.

    Args:
        status_dir: Output directory.
        report: The finished run.
        previous_success: Unix time of the last successful run before this one (carried forward on failure).
    """
    finished = report.finished_at or datetime.now(UTC)
    success = report.result == "ok"
    last_success = finished.timestamp() if success else previous_success
    document = {
        "result": report.result,
        "set_id": report.set_id,
        "started_at": report.started_at.isoformat(),
        "finished_at": finished.isoformat(),
        "duration_seconds": round((finished - report.started_at).total_seconds(), 3),
        "failed_step": None if success else report.step,
        "error": report.error,
        "snapshot_id": report.snapshot_id,
        "set_bytes": report.set_bytes,
        "bytes_added": report.bytes_added,
        "secrets_mode": report.secrets_mode,
        "tool_version": TOOL_VERSION,
        "last_success_timestamp": last_success,
        "destinations": [{"target": d.target, "ok": d.ok, "error": d.error} for d in report.destinations],
    }
    _write_atomic(status_dir / "status.json", json.dumps(document, indent=2) + "\n")
    lines = [
        "# HELP reqtrack_backup_last_run_success 1 if the last backup run succeeded, else 0.",
        "# TYPE reqtrack_backup_last_run_success gauge",
        f"reqtrack_backup_last_run_success {1 if success else 0}",
        "# HELP reqtrack_backup_last_run_timestamp_seconds Unix time the last backup run finished.",
        "# TYPE reqtrack_backup_last_run_timestamp_seconds gauge",
        f"reqtrack_backup_last_run_timestamp_seconds {finished.timestamp():.0f}",
        "# HELP reqtrack_backup_last_success_timestamp_seconds Unix time of the last fully successful backup run.",
        "# TYPE reqtrack_backup_last_success_timestamp_seconds gauge",
        f"reqtrack_backup_last_success_timestamp_seconds {last_success or 0:.0f}",
        "# HELP reqtrack_backup_duration_seconds Duration of the last backup run.",
        "# TYPE reqtrack_backup_duration_seconds gauge",
        f"reqtrack_backup_duration_seconds {document['duration_seconds']}",
        "# HELP reqtrack_backup_set_bytes Size of the last backup set before deduplication.",
        "# TYPE reqtrack_backup_set_bytes gauge",
        f"reqtrack_backup_set_bytes {report.set_bytes}",
        "# HELP reqtrack_backup_destination_up 1 if the last copy to the destination succeeded.",
        "# TYPE reqtrack_backup_destination_up gauge",
    ]
    for index, dest in enumerate(report.destinations, start=1):
        lines.append(f'reqtrack_backup_destination_up{{destination="{index}"}} {1 if dest.ok else 0}')
    _write_atomic(status_dir / "reqtrack-backup.prom", "\n".join(lines) + "\n")


def _previous_success(status_dir: Path) -> float | None:
    """Reads the last-success time from the previous `status.json`, tolerating its absence or damage."""
    try:
        value = json.loads((status_dir / "status.json").read_text()).get("last_success_timestamp")
    except (OSError, ValueError):
        return None
    return float(value) if isinstance(value, int | float) else None


def _postgres_version(db: Session) -> str:
    """The server's `major.minor` (e.g. `16.4`)."""
    return str(db.execute(text("SHOW server_version")).scalar()).split(" ")[0]


def _snapshot_session(engine: Engine) -> Any:
    """Opens the transaction that exports the snapshot the dump and the statistics both read."""
    return engine.connect().execution_options(isolation_level="REPEATABLE READ")


def run_backup(config: BackupConfig, deps: BackupDeps) -> RunReport:
    """Runs one backup end to end.

    Args:
        config: Tool settings.
        deps: The database, object store, restic wrapper and clock to use.

    Returns:
        The report (also written to `status.json`). Failures never raise: they are recorded in the report
        with `result == "failed"`.

    Raises:
        AlreadyRunning: If another run holds the lock (nothing is written).
    """
    redact = deps.restic.redact
    started = deps.now()
    set_id = new_set_id(started)
    report = RunReport(set_id=set_id, started_at=started, secrets_mode=config.secrets_mode.value)

    with run_lock(config.staging_dir):
        previous = _previous_success(config.status_dir)
        set_dir = config.staging_dir / "sets" / set_id
        previous_umask = os.umask(0o077)
        try:
            if set_dir.exists():
                shutil.rmtree(set_dir)
            (set_dir / "database").mkdir(parents=True, mode=0o700)
            _run_steps(config, deps, report, set_dir)
            report.result = "ok" if all(d.ok for d in report.destinations) else "failed"
            if report.result == "failed" and report.error is None:
                report.step = "copy"
                report.error = "one or more destinations failed"
        except BackupError as exc:
            report.step, report.error = exc.step, str(exc)
        except (ResticError, OSError) as exc:
            report.error = redact(str(exc))
        except Exception as exc:  # last resort: record the class, never the message (it may carry data)
            report.error = f"unexpected {type(exc).__name__}"
        finally:
            os.umask(previous_umask)
            shutil.rmtree(set_dir, ignore_errors=True)
            report.finished_at = deps.now()
            write_status(config.status_dir, report, previous)
    return report


def _run_steps(config: BackupConfig, deps: BackupDeps, report: RunReport, set_dir: Path) -> None:
    """The ordered steps of a run; raises on the first failure, with `report.step` naming the step reached."""
    redact, restic = deps.restic.redact, deps.restic
    components: dict[ComponentKind, ComponentEntry] = {}

    report.step = "config"
    require_password(config.password_file)
    if config.secrets_mode is SecretsMode.CONFIG:
        encrypt_config(config.env_file, config.config_age_recipient, set_dir / "env.age", redact)
        components[ComponentKind.CONFIG] = _entry(set_dir / "env.age", set_dir)

    report.step = "dump"
    dump_path = set_dir / "database" / "reqtrack.dump"
    with _snapshot_session(deps.engine) as exporter:
        snapshot_id = str(exporter.execute(text("SELECT pg_export_snapshot()")).scalar())
        deps.dumper(config, deps.db_url, snapshot_id, dump_path, redact)
        components[ComponentKind.DATABASE] = _entry(dump_path, set_dir)
        report.step = "stats"
        with Session(deps.engine) as db:
            stats: DrStats = collect_stats(db, deps.storage_for_probe, snapshot_id=snapshot_id, probe_encryption=deps.probe_encryption)
            postgres_version = _postgres_version(db)
            db.rollback()
        exporter.rollback()
    failures = probe_failures(stats)
    if failures:
        raise BackupError("stats", redact("source failed its own integrity probes: " + "; ".join(failures[:3])))

    objects: ObjectsSummary | None = None
    paths = [set_dir]
    report.step = "mirror"
    if deps.storage_backend == "s3":
        if deps.storage_client is None:
            raise BackupError("mirror", "STORAGE_BACKEND=s3 but no object-store client is available")
        mirror_root = config.staging_dir / "objects"
        mirror = ObjectMirror(deps.storage_client, deps.storage_bucket, mirror_root, config.staging_dir / "objects-state.json")
        result = mirror.sync()
        objects = ObjectsSummary(count=result.count, bytes=result.bytes)
        components[ComponentKind.OBJECTS] = ComponentEntry(path="objects", sha256=result.digest, bytes=result.bytes)
        paths.append(mirror_root)
    else:
        archive_local_files(config.local_files_dir, set_dir / "local_files.tar")
        components[ComponentKind.LOCAL_FILES] = _entry(set_dir / "local_files.tar", set_dir)

    from app.version import APP_VERSION, GIT_SHA

    finished = deps.now()
    manifest = BackupManifest(
        set_id=report.set_id,
        created_at=report.started_at,
        finished_at=finished,
        tool_version=TOOL_VERSION,
        app=AppIdentity(version=APP_VERSION, git_sha=GIT_SHA, image_tag=os.environ.get("IMAGE_TAG")),
        alembic_revision=stats.alembic_revision,
        postgres_version=postgres_version,
        storage_backend=deps.storage_backend,
        secrets_mode=config.secrets_mode,
        components=components,
        objects=objects,
        stats=stats,
    )
    (set_dir / MANIFEST_FILENAME).write_text(dump_manifest(manifest))
    report.set_bytes = sum(c.bytes for c in components.values())

    report.step = "snapshot"
    restic.ensure_repo(config.repository)
    stored = restic.backup(config.repository, paths, tags=[f"set:{report.set_id}", f"secrets:{config.secrets_mode.value}"], host=SNAPSHOT_HOST)
    report.snapshot_id, report.bytes_added = stored.snapshot_id, stored.bytes_added

    report.step = "retention"
    restic.forget(config.repository, config.retention)
    if config.check_subset:
        report.step = "check"
        restic.check(config.repository, read_data_subset=config.check_subset)

    for target in config.destinations:
        label = redact(target)
        try:
            restic.ensure_repo(target, from_repo=config.repository)
            restic.copy(config.repository, target, stored.snapshot_id)
            restic.forget(target, config.retention)
            report.destinations.append(DestinationResult(label, True))
        except ResticError as exc:
            report.destinations.append(DestinationResult(label, False, str(exc)))
    report.step = "done"
