"""
Module: services.dr_verify

The checks that prove a restored platform is working, run inside the restored stack's own backend
container by the restore-test (`scripts/restore_test.py`) once the application has started on the restored
database. They complement the restore tool's own verification, which compares the restored database with the
manifest before it replaces anything: these find what only a running application shows (a migration the new
image still wants to run, statistics that moved when the application started, a stored object that cannot be
read back, a configuration that would email real people, an API that does not answer).

Responsibilities:
- `migrations`: the database is at the manifest's Alembic revision and that revision is this image's head,
  so `alembic upgrade head` changes nothing.
- `statistics`: every table count and business statistic equals the manifest, recomputed with the same
  `dr_stats` code the backup used, after the application has been running.
- `file-objects`: every file record has its object, and a random sample reads back at its recorded size.
- `encrypted-columns`: every encrypted value decrypts with the key this stack runs with.
- `email-disabled`: the stack cannot send mail (`EMAIL_DELIVERY=disabled`), shown by attempting a send.
- `api-smoke`: the API answers as a real user of a project the restore holds: health, identity, the
  organisation and project lists, a record, a project search and a project export. `login` (optional) checks
  that a supplied account can sign in, which proves the stored password hashes verify.
- Always return one machine-readable report; a check that cannot run says so instead of passing.

Design decisions:
- Statistics are collected before the API checks, because signing in and exporting write audit rows.
- The API checks use a token minted for a user who manages a project that has records, rather than a
  password: the restored database's passwords are unknown to the test, and the token still exercises token
  validation against the restored `token_version` and the full authorisation path. `login` covers the password
  path only when credentials are supplied.
- A report holds check names, counts and ids only, never row content, names, addresses, tokens or secrets;
  the search text is taken from a record and is sent in the request body and never written anywhere.
- Every instant is UTC.

Dependencies: SQLAlchemy, httpx (the API calls), `services.dr_stats`, `services.dr_manifest`,
`services.dr_restore.code_revisions`, `services.email`, `security.create_access_token`.
"""

from __future__ import annotations

import io
import random
import zipfile
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.models.enums import ProjectRole
from app.models.file import FileAsset
from app.models.project import Project, UserProjectRole
from app.models.requirement import Requirement, RequirementVersion
from app.models.user import User
from app.security import create_access_token
from app.services.dr_manifest import BackupManifest
from app.services.dr_stats import DrStats, collect_stats, compare_stats
from app.storage_backends import FileStorageBackend

MAX_REPORTED_MISMATCHES = 100
"""Cap on statistics differences written to the report."""

DEFAULT_SAMPLE_SIZE = 20
"""Stored objects read back in full by the `file-objects` check."""


@dataclass
class Check:
    """One named check.

    Attributes:
        name: Stable check name (the list in the module docstring).
        ok: Whether it passed. A check that could not run is not ok.
        detail: One line, counts and ids only.
        data: Machine-readable specifics (mismatches, counts), never row content.
    """

    name: str
    ok: bool
    detail: str
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class VerifyReport:
    """The outcome of a verification run, as written to `verify-report.json`."""

    result: str = "failed"
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime | None = None
    checks: list[Check] = field(default_factory=list)

    def to_json_dict(self) -> dict[str, Any]:
        """The report as JSON-ready data (instants as ISO 8601 with offset)."""
        data = asdict(self)
        data["started_at"] = self.started_at.isoformat()
        data["finished_at"] = self.finished_at.isoformat() if self.finished_at else None
        return data


@dataclass
class LoginCredentials:
    """An account whose sign-in is exercised (`login` check); the password is never reported."""

    email: str
    password: str


def _check(name: str, fn: Callable[[], Check]) -> Check:
    """Runs one check and turns an unexpected exception into a failed check naming the exception class only."""
    try:
        return fn()
    except Exception as exc:  # a check must report, not crash the run; the message may carry data
        return Check(name, False, f"the check could not run ({type(exc).__name__})")


def check_migrations(actual: DrStats, manifest: BackupManifest, head_revisions: set[str]) -> Check:
    """The database is at the manifest's revision, and that revision is this image's head.

    Args:
        actual: Statistics recomputed on the running stack.
        manifest: The set's manifest.
        head_revisions: The Alembic heads of this image (core and module chains).
    """
    revision = actual.alembic_revision
    if revision != manifest.stats.alembic_revision:
        return Check("migrations", False, f"revision is {revision}, the set was taken at {manifest.stats.alembic_revision}")
    if revision not in head_revisions:
        return Check("migrations", False, f"revision {revision} is not this image's head, so a migration would still run")
    return Check("migrations", True, f"at revision {revision}; upgrade head changes nothing")


def check_statistics(actual: DrStats, manifest: BackupManifest, extra_rows: Mapping[str, int] | None = None) -> Check:
    """Every table count and business statistic equals the manifest.

    Args:
        actual: Statistics recomputed on the running stack.
        manifest: The set's manifest.
        extra_rows: Rows the restore itself is known to have written, as `{table: count}` (the audit event of
            clearing unreadable secrets). Only exactly these are allowed: one more or one fewer still fails.
    """
    expected = manifest.stats
    if extra_rows:
        expected = expected.model_copy(deep=True)
        for table, count in extra_rows.items():
            expected.tables[table] = expected.tables.get(table, 0) + count
    try:
        mismatches = compare_stats(expected, actual)
    except ValueError as exc:
        return Check("statistics", False, str(exc))
    tables = len(manifest.stats.tables)
    if not mismatches:
        allowed = f" (plus {sum(extra_rows.values())} audit rows the restore wrote)" if extra_rows else ""
        return Check("statistics", True, f"{tables} table counts and the business statistics equal the manifest{allowed}", {"tables": tables})
    first = mismatches[0]
    return Check(
        "statistics",
        False,
        f"{len(mismatches)} statistics differ from the manifest (first: {first.path} expected {first.expected!r}, got {first.actual!r})",
        {"mismatches": [m.model_dump() for m in mismatches[:MAX_REPORTED_MISMATCHES]]},
    )


def check_file_objects(db: Session, actual: DrStats, storage: FileStorageBackend, sample_size: int, rng: random.Random) -> Check:
    """Every file record has its object, and a random sample reads back at its recorded size.

    Args:
        db: A session on the restored database.
        actual: Statistics recomputed on the running stack (holds the existence probe).
        storage: The stack's storage backend.
        sample_size: How many objects to read in full.
        rng: Source of the random sample (a seeded one makes a failure reproducible).
    """
    files = actual.probes.files
    if files.skipped:
        return Check("file-objects", False, "the object-store probe was skipped")
    if files.missing:
        return Check(
            "file-objects",
            False,
            f"{files.missing} of {files.checked} file records have no stored object",
            {"missing_file_ids": files.missing_file_ids},
        )
    rows = db.execute(select(FileAsset.id, FileAsset.storage_key, FileAsset.size_bytes).where(FileAsset.storage_backend == storage.name)).all()
    sample = rng.sample(rows, min(sample_size, len(rows)))
    wrong: list[str] = []
    for file_id, key, size in sample:
        try:
            if len(storage.read(key)) != size:
                wrong.append(str(file_id))
        except FileNotFoundError:
            wrong.append(str(file_id))
    if wrong:
        return Check("file-objects", False, f"{len(wrong)} of {len(sample)} sampled objects are missing or differ in size", {"file_ids": wrong[:50]})
    return Check("file-objects", True, f"all {files.checked} file records have an object; {len(sample)} read back at their recorded size")


def check_encrypted_columns(actual: DrStats, *, key_supplied: bool, allow_unreadable: bool) -> Check:
    """Every encrypted value decrypts with the key the stack runs with.

    Args:
        actual: Statistics recomputed on the running stack.
        key_supplied: Whether `APP_SECRET_ENCRYPTION_KEY` is set; without it nothing can be judged.
        allow_unreadable: The restore was told to clear unreadable values, so none should remain either; this
            only affects the wording, since cleared values are gone and must not be found.
    """
    if not key_supplied:
        return Check("encrypted-columns", False, "APP_SECRET_ENCRYPTION_KEY is not set on this stack, so encrypted columns cannot be judged")
    columns = actual.probes.encrypted_columns
    unreadable = {name: probe.undecryptable for name, probe in columns.items() if probe.undecryptable}
    rows = sum(probe.rows for probe in columns.values())
    if unreadable:
        detail = ", ".join(f"{name} ({count})" for name, count in sorted(unreadable.items()))
        return Check("encrypted-columns", False, f"values the key cannot decrypt: {detail}", {"undecryptable": unreadable})
    suffix = " (unreadable values were cleared by the restore)" if allow_unreadable else ""
    return Check("encrypted-columns", True, f"{rows} encrypted values in {len(columns)} columns all decrypt{suffix}", {"rows": rows})


def check_email_disabled() -> Check:
    """A send attempt is refused before any connection is made, so the stack cannot reach real recipients."""
    import asyncio

    from app.services.email import EmailDeliveryDisabled, send_email_async

    try:
        asyncio.run(send_email_async("restore-test@invalid", "restore-test", "this message must never leave the stack"))
    except EmailDeliveryDisabled:
        return Check("email-disabled", True, "email delivery is disabled: a send attempt was refused before any connection")
    except Exception as exc:
        return Check("email-disabled", False, f"a send attempt was not refused up front ({type(exc).__name__}); EMAIL_DELIVERY is not disabled")
    return Check("email-disabled", False, "a send attempt succeeded; EMAIL_DELIVERY is not disabled")


def _smoke_target(db: Session) -> tuple[User, Project, Requirement] | None:
    """A user who manages a project that holds a record, so every API step can be exercised.

    Returns:
        `(user, project, requirement)`, or None when the restored platform has no such project (an empty
        installation, or no local account that manages a project).
    """
    managers = (ProjectRole.PROJECT_MANAGER, ProjectRole.PROJECT_ADMINISTRATOR)
    has_record = exists().where(Requirement.project_id == Project.id)
    row = db.execute(
        select(User, Project)
        .join(UserProjectRole, UserProjectRole.user_id == User.id)
        .join(Project, Project.id == UserProjectRole.project_id)
        .where(UserProjectRole.role.in_(managers), User.is_active.is_(True), has_record)
        .order_by(Project.created_at, User.created_at)
        .limit(1)
    ).first()
    if row is None:
        return None
    user, project = row
    requirement = db.scalars(select(Requirement).where(Requirement.project_id == project.id).order_by(Requirement.created_at).limit(1)).first()
    return (user, project, requirement) if requirement else None


def _search_term(text: str) -> str | None:
    """The first word of a record's name long enough to search for (2 or more characters), or None."""
    return next((word for word in text.replace("-", " ").split() if len(word) >= 2 and word.isalnum()), None)


def check_api(db: Session, client: httpx.Client) -> Check:
    """Exercises the running API as a manager of a project that has records.

    Steps (each named in the detail on failure): health; identity; the organisation list; the project list; a
    record; a project search that finds it; a project export that is a valid archive. Responses are
    inspected, never stored.

    Args:
        db: A session on the restored database (picks the user, project and record).
        client: An HTTP client whose base URL is the stack's own backend.
    """
    health = client.get("/health")
    if health.status_code != 200:
        return Check("api-smoke", False, f"/health answered {health.status_code}")
    target = _smoke_target(db)
    if target is None:
        return Check(
            "api-smoke", True, "/health answers; the platform holds no project with a record to open (nothing further to exercise)", {"skipped": True}
        )
    user, project, requirement = target
    headers = {"Authorization": f"Bearer {create_access_token(str(user.id), token_version=user.token_version)}"}
    steps = 1

    def get(path: str) -> httpx.Response:
        return client.get(path, headers=headers)

    me = get("/api/v1/auth/me")
    if me.status_code != 200:
        return Check("api-smoke", False, f"signed-in identity answered {me.status_code}: the restored token version or account was not accepted")
    steps += 1
    orgs = get("/api/v1/orgs?mine=true")
    if orgs.status_code != 200 or not orgs.json():
        return Check(
            "api-smoke",
            False,
            f"organisation list answered {orgs.status_code} with {len(orgs.json()) if orgs.status_code == 200 else 0} organisations",
        )
    steps += 1
    projects = get("/api/v1/projects")
    if projects.status_code != 200 or str(project.id) not in {p["id"] for p in projects.json()}:
        return Check("api-smoke", False, f"project list answered {projects.status_code} and did not include the project under test")
    steps += 1
    record = get(f"/api/v1/projects/{project.id}/requirements/{requirement.id}")
    if record.status_code != 200:
        return Check("api-smoke", False, f"opening a record answered {record.status_code}")
    steps += 1
    name = db.scalar(
        select(RequirementVersion.name).where(RequirementVersion.requirement_id == requirement.id, RequirementVersion.valid_to.is_(None))
    )
    term = _search_term(name or "")
    if term:
        found = client.post("/api/v1/search", headers=headers, json={"q": term, "scope": "project", "project_id": str(project.id)})
        if found.status_code != 200 or found.json().get("total", 0) < 1:
            return Check("api-smoke", False, f"project search answered {found.status_code} and found nothing for a word taken from a record")
        steps += 1
    export = get(f"/api/v1/projects/{project.id}/export")
    if export.status_code != 200:
        return Check("api-smoke", False, f"project export answered {export.status_code}")
    try:
        with zipfile.ZipFile(io.BytesIO(export.content)) as archive:
            if archive.testzip() is not None or not archive.namelist():
                return Check("api-smoke", False, "the project export is not a valid archive")
    except zipfile.BadZipFile:
        return Check("api-smoke", False, "the project export is not a zip archive")
    steps += 1
    return Check(
        "api-smoke",
        True,
        f"{steps} API steps passed as a project manager (health, identity, organisations, projects, record, search, export)",
        {"steps": steps},
    )


def check_login(client: httpx.Client, credentials: LoginCredentials) -> Check:
    """A supplied account signs in with its password, which proves the restored password hashes verify.

    A second-factor challenge counts as success: it is only issued after the password was accepted.
    """
    response = client.post("/api/v1/auth/login", json={"email": credentials.email, "password": credentials.password})
    if response.status_code != 200:
        return Check("login", False, f"sign-in with the supplied account answered {response.status_code}")
    body = response.json()
    if "access_token" in body:
        return Check("login", True, "the supplied account signed in with its password")
    if "challenge_token" in body:
        return Check("login", True, "the supplied account's password was accepted and a second-factor challenge was issued")
    return Check("login", False, "sign-in answered 200 without a token or a challenge")


def run_verification(
    manifest: BackupManifest,
    db: Session,
    storage: FileStorageBackend,
    client: httpx.Client,
    *,
    head_revisions: set[str],
    key_supplied: bool,
    allow_unreadable_secrets: bool = False,
    extra_rows: Mapping[str, int] | None = None,
    login: LoginCredentials | None = None,
    sample_size: int = DEFAULT_SAMPLE_SIZE,
    rng: random.Random | None = None,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> VerifyReport:
    """Runs every check against a running restored stack.

    Args:
        manifest: The set's manifest.
        db: A session with no transaction begun yet (statistics need the first statement to set the isolation).
        storage: The stack's storage backend.
        client: An HTTP client whose base URL is the stack's own backend.
        head_revisions: The Alembic heads of this image.
        key_supplied: Whether `APP_SECRET_ENCRYPTION_KEY` is set on this stack.
        allow_unreadable_secrets: The restore was run with `--clear-unreadable-secrets` (wording only).
        extra_rows: Rows the restore wrote itself, `{table: count}`, allowed on top of the manifest's counts.
        login: An account to sign in with (optional).
        sample_size: Objects read back in full.
        rng: Source of the object sample.
        now: Clock (UTC).

    Returns:
        The report; `result` is `ok` only when every check passed. Failures never raise.
    """
    report = VerifyReport(started_at=now())
    try:
        actual = collect_stats(db, storage, probe_encryption=key_supplied)
    except Exception as exc:  # the stack could not be read at all: report it, there is nothing to compare
        report.checks.append(Check("statistics", False, f"the statistics could not be collected ({type(exc).__name__})"))
    else:
        report.checks.append(_check("migrations", lambda: check_migrations(actual, manifest, head_revisions)))
        report.checks.append(_check("statistics", lambda: check_statistics(actual, manifest, extra_rows)))
        report.checks.append(_check("file-objects", lambda: check_file_objects(db, actual, storage, sample_size, rng or random.Random())))
        report.checks.append(
            _check("encrypted-columns", lambda: check_encrypted_columns(actual, key_supplied=key_supplied, allow_unreadable=allow_unreadable_secrets))
        )
    db.rollback()
    report.checks.append(_check("email-disabled", check_email_disabled))
    report.checks.append(_check("api-smoke", lambda: check_api(db, client)))
    if login is not None:
        report.checks.append(_check("login", lambda: check_login(client, login)))
    report.result = "ok" if all(c.ok for c in report.checks) else "failed"
    report.finished_at = now()
    return report
