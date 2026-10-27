"""
Module: services.report_run_jobs

Background runs of custom reports: a run that is too big to answer inside a request is queued, produced by
the leader process, stored for a limited time and announced with a notification.

Responsibilities:
- `enqueue`: records the request as a `queued` `GeneratedReport` row (the job) after checking it can be
  produced and the requester has not queued too many.
- `run_job` / `run_next`: claims a queued job, runs it as the requester with the background limits, renders
  it, stores the file, fills in the provenance and notifies the requester (`ready` or `failed`).
- `expire`: deletes stored files past their expiry (row kept as `expired`), reaps jobs stuck `running`, and
  deletes provenance rows older than the platform retention.
- `list_for`, `get_for`, `read_output`, `delete_output`: the requester's view of their own runs.
- `run_job_loop`: the singleton loop that drives all of the above (started through the lifespan's
  `start_singletons`, so exactly one process works the queue).

Design decisions:
- **The request is the row.** The layout version, format and parameters pinned at enqueue time are on the
  `GeneratedReport` row, so a job runs the layout as it was when the person asked, even if it is edited in
  the queue. Nothing about the layout's text is copied.
- **Runs as the requester, re-checked at run time.** The job loads the requester and re-checks that they are
  still active, still reach the project or organisation and the layout, and runs with their resolver, so a
  report never contains more than they can read *now*. A requester who lost access gets a failure, not a file.
- **Only the requester downloads, and only while the file exists.** Stored output is Confidential data at
  rest; there is no organisation-wide listing. Download re-checks access (same checks as run time) and the
  expiry, so an expired file is refused even if the expiry job has not yet reached it.
- **One queue, one leader.** The loop claims rows with `FOR UPDATE SKIP LOCKED` and runs one job at a time in
  a worker thread (evaluation and rendering are blocking). A job left `running` longer than its own deadline
  (the leader died) is marked `failed`, never silently re-run.
- **Retention is the organisation's, capped by the platform.** `effective_retention_days` takes the
  organisation's setting or the platform default and never exceeds the platform ceiling. Expiry deletes the
  object first and the row's file columns after, so a failed delete is retried on the next pass.
- **Messages are safe to show.** A failure stores a fixed sentence per cause (limits, access, render), never
  an exception string, because the row is readable by the requester and must not carry record content.

Dependencies: `services.custom_report_run`, `services.files` (storage backend), `services.notifications`,
`models.generated_report`.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import SessionLocal
from app.models.generated_report import (
    SCOPE_PROJECT,
    STATUS_EXPIRED,
    STATUS_FAILED,
    STATUS_QUEUED,
    STATUS_READY,
    STATUS_RUNNING,
    GeneratedReport,
)
from app.models.notification import NotificationType
from app.models.organization import Organization
from app.models.project import Project
from app.models.report_layout import ReportLayout, ReportLayoutVersion
from app.models.user import User
from app.services import custom_report_run, report_layout_scope, report_layouts
from app.services.files import get_storage_backend
from app.services.notifications import notify
from app.services.rbac import get_effective_org_roles, get_effective_project_roles
from app.services.report_document import load_report_template
from app.services.report_layout_eval import ASYNC_TIMEOUT_SECONDS, LayoutLimitError, LayoutTimeoutError

logger = logging.getLogger(__name__)

#: Most queued or running background runs one person may have at a time.
MAX_ACTIVE_PER_USER = 5
#: Largest file a background run may store; a bigger render fails rather than fill the object store.
MAX_OUTPUT_BYTES = 200 * 1024 * 1024
#: Seconds between looks at the queue when it was empty.
POLL_SECONDS = 5.0
#: Seconds between expiry passes.
EXPIRY_INTERVAL_SECONDS = 15 * 60
#: How long past its own deadline a `running` job is given before it is treated as lost.
_RUNNING_GRACE = timedelta(minutes=2)
_ACTIVE = (STATUS_QUEUED, STATUS_RUNNING)

FAILURE_ACCESS = "You no longer have access to run this report."
FAILURE_LIMITS = "The report is too large to produce even in the background. Narrow the layout or select fewer projects."
FAILURE_TIME = "The report took too long to produce. Narrow the layout or select fewer projects."
FAILURE_OUTPUT = "The finished file is too large to keep. Narrow the layout or choose another format."
FAILURE_OTHER = "The report could not be produced."
FAILURE_LOST = "The report was interrupted and was not produced. Run it again."


class TooManyActiveRunsError(RuntimeError):
    """The requester already has `MAX_ACTIVE_PER_USER` background runs queued or running."""


class RunNotAvailableError(LookupError):
    """The run does not exist, is not the caller's, has no stored file or the caller lost access."""


def effective_retention_days(organization: Organization) -> int:
    """How many days the stored output of this organisation's background runs is kept.

    Args:
        organization: The organisation.

    Returns:
        Its own setting or the platform default, never more than the platform ceiling, at least 1.
    """
    settings = get_settings()
    wanted = organization.report_output_retention_days or settings.report_output_default_retention_days
    return max(1, min(wanted, settings.report_output_max_retention_days))


def _now() -> datetime:
    return datetime.now(UTC)


def enqueue(
    db: Session, user: User, *, organization: Organization, project: Project | None, layout: ReportLayout,
    version: ReportLayoutVersion, fmt: str, report_template_id: uuid.UUID | None, include_children: bool = False,
    requested_project_ids: Sequence[uuid.UUID] | None = None, variables: Mapping[str, Any] | None = None,
) -> GeneratedReport:
    """Queues a background run (the caller commits).

    The route has already authorised the caller for the project or organisation and the layout, checked the
    format and the branding template.

    Args:
        db: Active session.
        user: The requester.
        organization: The organisation.
        project: The project of a project-level run, `None` for an organisation-wide run.
        layout: The layout to run.
        version: The version to pin (the layout's current one).
        fmt: A renderer format of the layout's family.
        report_template_id: The branding template, if any.
        include_children: Also read readable child projects (project-level run).
        requested_project_ids: The projects selected for an organisation-wide run, `None` for all readable.
        variables: The layout's run-time variable values, already resolved by the route (so a bad value fails the
            request, not the job); the job runs with exactly these.

    Returns:
        The new `queued` row.

    Raises:
        TooManyActiveRunsError: The requester already has `MAX_ACTIVE_PER_USER` active background runs.
    """
    active = db.scalar(
        select(func.count()).select_from(GeneratedReport).where(
            GeneratedReport.requested_by == user.id, GeneratedReport.status.in_(_ACTIVE)
        )
    )
    if (active or 0) >= MAX_ACTIVE_PER_USER:
        raise TooManyActiveRunsError(
            f"You already have {MAX_ACTIVE_PER_USER} reports being prepared. Wait for one to finish."
        )
    row = GeneratedReport(
        organization_id=organization.id, project_id=project.id if project else None,
        scope=SCOPE_PROJECT if project else "organization", layout_id=layout.id, layout_name=layout.name,
        layout_version=version.version, tree_hash=version.tree_hash, requested_by=user.id, created_at=_now(),
        format=fmt, engine_version=custom_report_run.ENGINE_VERSION,
        params=custom_report_run.run_params(report_template_id, include_children, requested_project_ids, variables),
        scope_project_ids=[str(project.id)] if project else [], widgets=[], record_counts={}, stats={},
        source_digest="", status=STATUS_QUEUED,
    )
    db.add(row)
    return row


# --- running ---------------------------------------------------------------------------------------------------


def _claim(db: Session) -> GeneratedReport | None:
    """Marks the oldest queued job `running` and returns it (committed), or `None` when the queue is empty."""
    row = db.scalar(
        select(GeneratedReport).where(GeneratedReport.status == STATUS_QUEUED)
        .order_by(GeneratedReport.created_at).limit(1).with_for_update(skip_locked=True)
    )
    if row is None:
        return None
    row.status = STATUS_RUNNING
    row.started_at = _now()
    db.commit()
    return row


def _can_run(db: Session, user: User | None, row: GeneratedReport, organization: Organization | None) -> bool:
    """Whether the requester can still run what the job asks (active account, organisation, membership)."""
    if user is None or not user.is_active or user.is_archived or organization is None or not organization.is_active:
        return False
    if row.scope == SCOPE_PROJECT:
        return row.project_id is not None and bool(get_effective_project_roles(db, user.id, row.project_id))
    return bool(get_effective_org_roles(db, user.id, organization.id))


def _fail(db: Session, row: GeneratedReport, message: str) -> None:
    row.status = STATUS_FAILED
    row.finished_at = _now()
    row.error = message
    db.commit()
    _announce(db, row)


def _announce(db: Session, row: GeneratedReport) -> None:
    """Tells the requester their report is ready or could not be produced (never fails the job)."""
    try:
        user = db.get(User, row.requested_by) if row.requested_by else None
        if user is None:
            return
        ready = row.status == STATUS_READY
        notify(
            db, user, notification_type=NotificationType.REPORT_RUN_FINISHED,
            title=f"Report ready: {row.layout_name}" if ready else f"Report could not be produced: {row.layout_name}",
            body=(
                f"Your {row.format.upper()} report is ready to download until "
                f"{row.expires_at.strftime('%Y-%m-%d %H:%M') if row.expires_at else 'it expires'} UTC."
                if ready else (row.error or FAILURE_OTHER)
            ),
            project_id=row.project_id, entity_type="generated_report", entity_id=str(row.id),
        )
        db.commit()
    except Exception:  # noqa: BLE001 - a notification problem must not turn a finished job into a failed one
        db.rollback()
        logger.exception("Could not notify about report run %s", row.id)


def run_job(db: Session, row: GeneratedReport) -> None:
    """Produces a claimed job: runs the layout as the requester, stores the file and announces the result.

    Every outcome is recorded on the row and ends in a notification; nothing is raised for a failed report.

    Args:
        db: Active session.
        row: A job just claimed (`running`).
    """
    user = db.get(User, row.requested_by) if row.requested_by else None
    organization = db.get(Organization, row.organization_id)
    if not _can_run(db, user, row, organization):
        return _fail(db, row, FAILURE_ACCESS)
    assert user is not None and organization is not None
    layout = db.get(ReportLayout, row.layout_id)
    version = report_layouts.get_version(db, row.layout_id, row.layout_version) if layout else None
    project = db.get(Project, row.project_id) if row.project_id else None
    if layout is None or version is None or (row.scope == SCOPE_PROJECT and project is None):
        return _fail(db, row, FAILURE_ACCESS)
    if project is not None:
        scoped = report_layout_scope.reachable_layout(db, project, layout.id)
        if scoped is None or scoped.hidden:
            return _fail(db, row, FAILURE_ACCESS)
    elif layout.organization_id != organization.id or layout.project_id is not None:
        return _fail(db, row, FAILURE_ACCESS)
    params = row.params
    template = None
    if params.get("report_template_id"):
        template = load_report_template(db, organization.id, uuid.UUID(params["report_template_id"]))
    requested = [uuid.UUID(p) for p in params["requested_project_ids"]] if params.get("requested_project_ids") is not None else None
    try:
        if project is not None:
            run = custom_report_run.run_project_layout(
                db, user, project, layout, version, include_children=bool(params.get("include_children")), background=True,
                variables=params.get("variables"),
            )
        else:
            run = custom_report_run.run_organization_layout(
                db, user, organization, layout, version, project_ids=requested, background=True, variables=params.get("variables"),
            )
        rendered = custom_report_run.render_file(db, run, row.format, template)
    except LayoutTimeoutError:
        return _fail(db, row, FAILURE_TIME)
    except LayoutLimitError:
        return _fail(db, row, FAILURE_LIMITS)
    except (custom_report_run.ProjectsNotInScopeError, custom_report_run.NoProjectsToRunError):
        return _fail(db, row, FAILURE_ACCESS)
    except Exception as exc:  # noqa: BLE001 - recorded as a fixed sentence
        # Only the exception type is logged: its message or traceback can quote record content.
        logger.error("Background report run %s failed (%s)", row.id, type(exc).__name__)
        db.rollback()
        return _fail(db, row, FAILURE_OTHER)
    if len(rendered.content) > MAX_OUTPUT_BYTES:
        return _fail(db, row, FAILURE_OUTPUT)
    key = f"report-runs/{organization.id}/{row.id}.{rendered.extension}"
    try:
        get_storage_backend().save(key, rendered.content)
    except Exception as exc:  # noqa: BLE001 - storage outage: the same fixed sentence
        logger.error("Could not store the output of report run %s (%s)", row.id, type(exc).__name__)
        return _fail(db, row, FAILURE_OTHER)
    for name, value in custom_report_run.provenance_fields(
        run, report_template_id=template.id if template else None, include_children=bool(params.get("include_children")),
        requested_project_ids=requested,
    ).items():
        if name != "created_at":  # when it was asked for, not when evaluation began
            setattr(row, name, value)
    now = _now()
    row.status = STATUS_READY
    row.finished_at = now
    row.expires_at = now + timedelta(days=effective_retention_days(organization))
    row.output_key = key
    row.output_filename = f"{custom_report_run.file_stem(run)}.{rendered.extension}"
    row.output_size = len(rendered.content)
    db.commit()
    _announce(db, row)


def run_next() -> bool:
    """Claims and produces one queued job in its own session.

    Returns:
        Whether a job was found (so the loop asks again at once rather than waiting).
    """
    db = SessionLocal()
    try:
        row = _claim(db)
        if row is None:
            return False
        try:
            run_job(db, row)
        except Exception as exc:  # noqa: BLE001 - last resort: a job must never stay `running` after its attempt
            logger.error("Background report run %s crashed (%s)", row.id, type(exc).__name__)
            db.rollback()
            _fail(db, row, FAILURE_OTHER)
        return True
    finally:
        db.close()


# --- expiry ----------------------------------------------------------------------------------------------------


def expire(db: Session, *, now: datetime | None = None) -> dict[str, int]:
    """One maintenance pass: expire stored files, reap lost jobs and delete old provenance rows.

    Args:
        db: Active session.
        now: The time to judge against (UTC); defaults to the current time.

    Returns:
        Counts: `expired` (files deleted), `lost` (jobs marked failed), `purged` (provenance rows deleted).
    """
    now = now or _now()
    expired = 0
    backend = get_storage_backend()
    for row in db.scalars(
        select(GeneratedReport).where(GeneratedReport.status == STATUS_READY, GeneratedReport.expires_at <= now)
    ).all():
        try:
            if row.output_key:
                backend.delete(row.output_key)
        except Exception:  # noqa: BLE001 - leave the row `ready`; the next pass retries
            logger.exception("Could not delete the stored output of report run %s", row.id)
            continue
        _clear_output(row, STATUS_EXPIRED)
        expired += 1
    lost_before = now - timedelta(seconds=ASYNC_TIMEOUT_SECONDS) - _RUNNING_GRACE
    lost = 0
    for row in db.scalars(
        select(GeneratedReport).where(GeneratedReport.status == STATUS_RUNNING, GeneratedReport.started_at < lost_before)
    ).all():
        row.status, row.finished_at, row.error = STATUS_FAILED, now, FAILURE_LOST
        lost += 1
    cutoff = now - timedelta(days=get_settings().report_run_record_retention_days)
    purged = db.execute(
        delete(GeneratedReport).where(
            GeneratedReport.created_at < cutoff, GeneratedReport.status.notin_([*_ACTIVE, STATUS_READY])
        )
    ).rowcount
    db.commit()
    return {"expired": expired, "lost": lost, "purged": purged or 0}


def _clear_output(row: GeneratedReport, status: str) -> None:
    row.status = status
    row.output_key = None
    row.output_size = None


# --- the requester's view -------------------------------------------------------------------------------------


def list_for(db: Session, user: User, organization_id: uuid.UUID | None = None, *, limit: int = 50) -> list[GeneratedReport]:
    """The caller's own background runs (in one organisation, or all), newest first.

    Args:
        db: Active session.
        user: The caller.
        organization_id: Restrict to this organisation, or `None` for all.
        limit: Most rows to return.

    Returns:
        Their runs that were queued in the background (those with a job state other than `completed`).
    """
    query = select(GeneratedReport).where(GeneratedReport.requested_by == user.id, GeneratedReport.status != "completed")
    if organization_id is not None:
        query = query.where(GeneratedReport.organization_id == organization_id)
    return list(db.scalars(query.order_by(GeneratedReport.created_at.desc()).limit(limit)).all())


def get_for(db: Session, user: User, run_id: uuid.UUID) -> GeneratedReport:
    """One of the caller's own background runs.

    Raises:
        RunNotAvailableError: No such run, or it belongs to someone else (the two look the same).
    """
    row = db.get(GeneratedReport, run_id)
    if row is None or row.requested_by != user.id or row.status == "completed":
        raise RunNotAvailableError("Report not found.")
    return row


def read_output(db: Session, user: User, run_id: uuid.UUID) -> tuple[GeneratedReport, bytes]:
    """The stored file of one of the caller's runs, after re-checking that they may still have it.

    Args:
        db: Active session.
        user: The caller.
        run_id: The run.

    Returns:
        The row and the file's bytes.

    Raises:
        RunNotAvailableError: Not the caller's, not `ready`, past its expiry, the file is gone, or the caller
            no longer reaches the project or organisation the report covers.
    """
    row = get_for(db, user, run_id)
    organization = db.get(Organization, row.organization_id)
    if row.status != STATUS_READY or row.output_key is None or (row.expires_at is not None and row.expires_at <= _now()):
        raise RunNotAvailableError("This report is no longer available.")
    if not _can_run(db, user, row, organization):
        raise RunNotAvailableError("This report is no longer available.")
    try:
        return row, get_storage_backend().read(row.output_key)
    except FileNotFoundError as exc:
        raise RunNotAvailableError("This report is no longer available.") from exc


def delete_output(db: Session, user: User, run_id: uuid.UUID) -> GeneratedReport:
    """Deletes the stored file of one of the caller's runs now (the row stays as provenance, `expired`).

    A queued run is cancelled instead (marked `failed` as cancelled); a running one cannot be stopped.

    Raises:
        RunNotAvailableError: Not the caller's run.
        ValueError: The run is being produced and cannot be removed yet.
    """
    row = get_for(db, user, run_id)
    if row.status == STATUS_RUNNING:
        raise ValueError("This report is being prepared and cannot be removed yet.")
    if row.status == STATUS_QUEUED:
        row.status, row.finished_at, row.error = STATUS_FAILED, _now(), "Cancelled."
    elif row.status == STATUS_READY:
        if row.output_key:
            get_storage_backend().delete(row.output_key)
        _clear_output(row, STATUS_EXPIRED)
        row.expires_at = _now()
    db.commit()
    return row


# --- the loop --------------------------------------------------------------------------------------------------


async def run_job_loop() -> None:
    """Works the queue forever and runs the expiry pass on its interval (leader process only).

    A job runs in a worker thread so the event loop keeps serving. A failure in one pass is logged and the
    loop carries on.
    """
    last_expiry = 0.0
    loop = asyncio.get_running_loop()
    while True:
        try:
            found = await asyncio.to_thread(run_next)
            if loop.time() - last_expiry >= EXPIRY_INTERVAL_SECONDS:
                last_expiry = loop.time()

                def _pass() -> None:
                    db = SessionLocal()
                    try:
                        expire(db)
                    finally:
                        db.close()

                await asyncio.to_thread(_pass)
            if not found:
                await asyncio.sleep(POLL_SECONDS)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - the queue loop must outlive any single failure
            logger.exception("Report run queue pass failed")
            await asyncio.sleep(POLL_SECONDS)


__all__ = [
    "EXPIRY_INTERVAL_SECONDS", "MAX_ACTIVE_PER_USER", "MAX_OUTPUT_BYTES", "RunNotAvailableError",
    "TooManyActiveRunsError", "delete_output", "effective_retention_days", "enqueue",
    "expire", "get_for", "list_for", "read_output", "run_job", "run_job_loop", "run_next",
]
