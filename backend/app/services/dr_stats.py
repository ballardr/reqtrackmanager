"""
Module: services.dr_stats

The disaster-recovery statistics document: one JSON-serialisable summary of a database and its file store
that the backup tool records in the manifest and the restore verifier recomputes, so "the restore matches
the source" is decided by the same code on both sides.

Responsibilities:
- Count every table found in the database catalogue (a table a new module adds is covered with no list to
  edit) and the Alembic revision.
- Summarise the business content (organisations, users, projects, groups, records per registered artefact
  type, links, file records and bytes).
- Run integrity probes: every file record resolves to a stored object, and every encrypted column decrypts
  with the configured key (so a wrong or missing `APP_SECRET_ENCRYPTION_KEY` is caught, not mistaken for
  "no secret configured").
- Compare two documents (`compare_stats`) and list the probe failures of one (`probe_failures`).

Design decisions:
- Counts and ids only: no row content, filename, storage key or secret ever enters the document (the
  data classification policy treats those as Confidential or Restricted). A missing file is named by its
  file-record id.
- Deterministic: no timestamps or host names, so two documents of the same data are equal. Volatile
  identity (when, which image) belongs to the manifest.
- Consistent with a dump: `collect_stats` reads inside one REPEATABLE READ transaction, optionally joined
  to the snapshot a `pg_dump --snapshot` run exported, so the counts match the dump exactly while the system
  is live. Object-store probes cannot join that snapshot; they are applied to the snapshot's file rows.
- Records per type are counted through each type's registered search provider (its table, id column and
  standing conditions), the one declaration every artefact type already makes; a type without one is listed
  in `uncounted_types` rather than silently omitted (the table counts still cover its rows).

Dependencies: SQLAlchemy, `app.models` (metadata), `app.modules.registry`, `app.models.encrypted_type`,
`app.storage_backends`.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import String, cast, func, select, text
from sqlalchemy.orm import Session

import app.models  # noqa: F401  (populates Base.metadata)
from app.database import Base
from app.models.encrypted_type import EncryptedString, decrypts_with_current_key
from app.models.file import FileAsset
from app.models.organization import Organization, OrgGroup
from app.models.project import Project, ProjectGroup
from app.models.relationship import ArtefactLink
from app.models.user import User
from app.modules.registry import (
    get_all_registered_artefact_types,
    get_module_registry,
    get_search_providers,
    import_all_module_models,
)
from app.storage_backends import FileStorageBackend

STATS_VERSION = 1
"""Bumped when the shape of `DrStats` changes incompatibly; a comparison across versions is refused."""

MAX_LISTED_IDS = 50
"""Cap on file-record ids named in a failing probe, so a mass loss does not produce a huge document."""

_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class UserStats(BaseModel):
    """User headcount. `server_admins` is a subset of `total`."""

    total: int
    active: int
    inactive: int
    server_admins: int


class GroupStats(BaseModel):
    """Organisation and project group counts."""

    organization: int
    project: int


class FileStats(BaseModel):
    """File records and the bytes they declare (from the database, not measured from storage)."""

    records: int
    bytes: int


class BusinessStats(BaseModel):
    """Counts a person recognises: what the platform holds, not how it is stored."""

    organizations: int
    users: UserStats
    projects: int
    groups: GroupStats
    records: dict[str, int] = Field(description="Records per registered artefact type, archived ones included.")
    uncounted_types: list[str] = Field(description="Registered artefact types with no search provider, so not counted here.")
    links: int
    files: FileStats


class FileProbe(BaseModel):
    """Whether every file record resolves to a stored object.

    Attributes:
        checked: Records probed (those held by the configured storage backend).
        missing: Records whose object is absent.
        other_backend: Records held by a backend other than the configured one; not probed.
        missing_file_ids: Ids of up to `MAX_LISTED_IDS` missing records (ids only, never keys or names).
        skipped: True when the probe was not run (no storage access), in which case it neither passes nor fails.
    """

    checked: int
    missing: int
    other_backend: int
    missing_file_ids: list[str]
    skipped: bool = False


class EncryptedColumnProbe(BaseModel):
    """Decrypt result for one encrypted column (`table.column`)."""

    rows: int = Field(description="Non-null values stored.")
    undecryptable: int = Field(description="Values the configured key cannot decrypt.")


class Probes(BaseModel):
    """Integrity probes; a restore is healthy only when `probe_failures` is empty."""

    files: FileProbe
    encrypted_columns: dict[str, EncryptedColumnProbe]


class DrStats(BaseModel):
    """The complete statistics document (see the module docstring)."""

    stats_version: int = STATS_VERSION
    alembic_revision: str | None = Field(description="The `alembic_version` row; null when the table is absent or empty.")
    tables: dict[str, int] = Field(description="Exact row count of every base table in the `public` schema.")
    business: BusinessStats
    probes: Probes


class StatsMismatch(BaseModel):
    """One difference between an expected and an actual document, at a dotted path."""

    path: str
    expected: Any
    actual: Any


def _quote(identifier: str) -> str:
    """Quotes a catalogue identifier for interpolation.

    Args:
        identifier: A table name read from `information_schema`.

    Returns:
        The double-quoted identifier.

    Raises:
        ValueError: If it contains a character outside `[A-Za-z0-9_]` (catalogue names here are fixed by
            migrations; anything else is refused rather than escaped).
    """
    if not _SAFE_IDENTIFIER.match(identifier):
        raise ValueError(f"Unexpected table name in catalogue: {identifier!r}")
    return f'"{identifier}"'


def _alembic_revision(db: Session, tables: dict[str, int]) -> str | None:
    """Reads the single Alembic revision, or None when the version table is absent or empty."""
    if tables.get("alembic_version", 0) == 0:
        return None
    return db.execute(text("SELECT version_num FROM alembic_version LIMIT 1")).scalar_one_or_none()


def table_counts(db: Session) -> dict[str, int]:
    """Counts every base table in the `public` schema, discovered from the catalogue.

    Args:
        db: A session inside the transaction whose view should be counted.

    Returns:
        `{table name: row count}`, sorted by name.
    """
    names = db.execute(
        text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' AND table_type = 'BASE TABLE' ORDER BY table_name")
    ).scalars()
    return {name: db.execute(text(f"SELECT count(*) FROM {_quote(name)}")).scalar_one() for name in list(names)}


def _record_counts(db: Session) -> tuple[dict[str, int], list[str]]:
    """Counts records per registered artefact type through each type's search provider.

    Returns:
        `({type: count}, [types with no provider])`, both ordered by type.
    """
    providers = get_search_providers()
    counts: dict[str, int] = {}
    uncounted: list[str] = []
    for artefact_type in sorted(get_all_registered_artefact_types()):
        provider = providers.get(artefact_type)
        if provider is None:
            uncounted.append(artefact_type)
            continue
        query = select(func.count(provider.columns.id)).select_from(provider.from_clause).where(*provider.where)
        counts[artefact_type] = db.execute(query).scalar_one()
    return counts, uncounted


def business_stats(db: Session) -> BusinessStats:
    """Summarises the platform's content (see `BusinessStats`)."""
    users_total = db.scalar(select(func.count()).select_from(User)) or 0
    users_active = db.scalar(select(func.count()).select_from(User).where(User.is_active.is_(True))) or 0
    server_admins = db.scalar(select(func.count()).select_from(User).where(User.is_server_admin.is_(True))) or 0
    records, uncounted = _record_counts(db)
    return BusinessStats(
        organizations=db.scalar(select(func.count()).select_from(Organization)) or 0,
        users=UserStats(total=users_total, active=users_active, inactive=users_total - users_active, server_admins=server_admins),
        projects=db.scalar(select(func.count()).select_from(Project)) or 0,
        groups=GroupStats(
            organization=db.scalar(select(func.count()).select_from(OrgGroup)) or 0,
            project=db.scalar(select(func.count()).select_from(ProjectGroup)) or 0,
        ),
        records=records,
        uncounted_types=uncounted,
        links=db.scalar(select(func.count()).select_from(ArtefactLink)) or 0,
        files=FileStats(
            records=db.scalar(select(func.count()).select_from(FileAsset)) or 0,
            bytes=int(db.scalar(select(func.coalesce(func.sum(FileAsset.size_bytes), 0))) or 0),
        ),
    )


def probe_files(db: Session, storage: FileStorageBackend | None) -> FileProbe:
    """Checks that each file record's object exists in the configured storage backend.

    Args:
        db: A session inside the snapshot being described.
        storage: The configured backend, or None to skip (no storage access from here).

    Returns:
        The probe result; a record held by a different backend than `storage` is counted, not probed.

    Raises:
        Exception: Whatever `storage.exists` raises for a failure other than "absent" (an unreachable store
            must fail the run, not report every file missing or present).
    """
    if storage is None:
        return FileProbe(checked=0, missing=0, other_backend=0, missing_file_ids=[], skipped=True)
    checked = missing = other = 0
    missing_ids: list[str] = []
    rows = db.execute(select(FileAsset.id, FileAsset.storage_backend, FileAsset.storage_key).order_by(FileAsset.id)).yield_per(500)
    for file_id, backend_name, key in rows:
        if backend_name != storage.name:
            other += 1
            continue
        checked += 1
        if not storage.exists(key):
            missing += 1
            if len(missing_ids) < MAX_LISTED_IDS:
                missing_ids.append(str(file_id))
    return FileProbe(checked=checked, missing=missing, other_backend=other, missing_file_ids=missing_ids)


def encrypted_columns() -> list[tuple[str, str]]:
    """Every `EncryptedString` column in the loaded models, as `(table, column)`.

    Discovered from `Base.metadata` so a module's own encrypted column is probed with no list to edit.
    """
    import_all_module_models()
    found = [
        (table.name, column.name) for table in Base.metadata.sorted_tables for column in table.columns if isinstance(column.type, EncryptedString)
    ]
    return sorted(found)


def probe_encrypted_columns(db: Session, existing_tables: set[str]) -> dict[str, EncryptedColumnProbe]:
    """Tries to decrypt every stored value of every encrypted column with the configured key.

    Args:
        db: A session inside the snapshot being described.
        existing_tables: Tables present in the database; a model table not yet migrated is skipped.

    Returns:
        `{"table.column": EncryptedColumnProbe}`. Values are read as raw ciphertext and never returned.
    """
    result: dict[str, EncryptedColumnProbe] = {}
    for table_name, column_name in encrypted_columns():
        if table_name not in existing_tables:
            continue
        column = Base.metadata.tables[table_name].c[column_name]
        values = db.execute(select(cast(column, String)).where(column.is_not(None))).scalars()
        rows = bad = 0
        for value in values:
            rows += 1
            if not decrypts_with_current_key(value):
                bad += 1
        result[f"{table_name}.{column_name}"] = EncryptedColumnProbe(rows=rows, undecryptable=bad)
    return result


def collect_stats(
    db: Session,
    storage: FileStorageBackend | None = None,
    *,
    snapshot_id: str | None = None,
    probe_encryption: bool = True,
) -> DrStats:
    """Collects the full statistics document inside one consistent REPEATABLE READ transaction.

    Args:
        db: A session with no transaction begun yet (the isolation level must be the first statement).
        storage: The configured storage backend to probe file records against, or None to skip that probe.
        snapshot_id: A snapshot id exported by another session (`pg_export_snapshot()`), to read exactly
            the data a `pg_dump --snapshot` run dumps. None reads the data as of now.
        probe_encryption: Whether to try decrypting encrypted columns. False when the caller was not given
            `APP_SECRET_ENCRYPTION_KEY` (the backup tool in `BACKUP_SECRETS_MODE=none`): the probe would blame a
            placeholder key, so it is left empty and the restore, which has the key, runs it.

    Returns:
        The document. The session's transaction is left open for the caller to close.

    Raises:
        sqlalchemy.exc.DBAPIError: If the database is unreachable or the snapshot id is invalid.
    """
    get_module_registry()
    import_all_module_models()
    db.connection(execution_options={"isolation_level": "REPEATABLE READ"})
    if snapshot_id is not None:
        db.execute(text(f"SET TRANSACTION SNAPSHOT {_quote_literal(snapshot_id)}"))
    tables = table_counts(db)
    return DrStats(
        alembic_revision=_alembic_revision(db, tables),
        tables=tables,
        business=business_stats(db),
        probes=Probes(
            files=probe_files(db, storage),
            encrypted_columns=probe_encrypted_columns(db, set(tables)) if probe_encryption else {},
        ),
    )


def _quote_literal(value: str) -> str:
    """Quotes a snapshot id as an SQL literal (`SET TRANSACTION SNAPSHOT` takes no bind parameter).

    Raises:
        ValueError: If it is not made of the characters Postgres uses in a snapshot id (`00000003-0000001B-1`).
    """
    if not re.fullmatch(r"[0-9A-Fa-f]+(-[0-9A-Fa-f]+)+", value):
        raise ValueError("Invalid snapshot id.")
    return f"'{value}'"


def probe_failures(stats: DrStats) -> list[str]:
    """Lists what is wrong with a document's integrity probes (empty means healthy).

    Args:
        stats: A collected document.

    Returns:
        One line per failing probe, naming ids and columns only.
    """
    failures: list[str] = []
    files = stats.probes.files
    if files.missing:
        failures.append(f"{files.missing} of {files.checked} file records have no stored object (e.g. {', '.join(files.missing_file_ids[:3])})")
    for column, probe in stats.probes.encrypted_columns.items():
        if probe.undecryptable:
            failures.append(f"{column}: {probe.undecryptable} of {probe.rows} values do not decrypt with the configured key")
    return failures


def _flatten(prefix: str, value: Any, out: dict[str, Any]) -> None:
    """Flattens nested dicts to `{dotted.path: leaf}` (lists are leaves)."""
    if isinstance(value, dict):
        for key in sorted(value):
            _flatten(f"{prefix}.{key}" if prefix else str(key), value[key], out)
    else:
        out[prefix] = value


def compare_stats(expected: DrStats, actual: DrStats) -> list[StatsMismatch]:
    """Differences between a source document and a restored one.

    The Alembic revision, every table count and every business statistic must be equal. Probes are not
    compared (they describe the target's health, judged by `probe_failures`).

    Args:
        expected: The document recorded at backup time.
        actual: The document recomputed after the restore.

    Returns:
        One `StatsMismatch` per differing path (a table present on only one side included), sorted by
        path; empty when they match.

    Raises:
        ValueError: If the documents have different `stats_version`s, which cannot be compared.
    """
    if expected.stats_version != actual.stats_version:
        raise ValueError(f"Cannot compare stats versions {expected.stats_version} and {actual.stats_version}.")
    left: dict[str, Any] = {}
    right: dict[str, Any] = {}
    for name, doc in ((left, expected), (right, actual)):
        dumped = doc.model_dump()
        _flatten("alembic_revision", dumped["alembic_revision"], name)
        _flatten("tables", dumped["tables"], name)
        _flatten("business", dumped["business"], name)
    return [
        StatsMismatch(path=path, expected=left.get(path), actual=right.get(path))
        for path in sorted(left.keys() | right.keys())
        if left.get(path) != right.get(path)
    ]
