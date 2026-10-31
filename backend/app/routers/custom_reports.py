"""
Module: routers.custom_reports

Runs a custom report layout (`services.custom_report_run`):

- `GET /api/v1/projects/{project_id}/custom-reports/{layout_id}/run?format=json|pdf|docx|odt|html|csv|xlsx|ods`: a layout the
  project can reach (its own, an ancestor's or the organisation's, unless the project hid it), for this
  project and, with `include_children`, its readable child projects.
- `GET /api/v1/orgs/{organization_id}/custom-reports/{layout_id}/run?format=...&project_ids=a,b`: an
  organisation layout run once per project the caller can read (or the selected ones) and merged.

Access: running needs only what reading the data needs (D13): membership of the project or organisation;
each record is then shown only if the caller's own project permissions allow it. Neither route needs the
manage-layouts permission. Every run writes a provenance row (`GeneratedReport`); a synchronous run stores no output.

A file run that passes the synchronous limits answers 409 with `detail.code == "async_required"`; the client then
queues it in the background:

- `POST .../custom-reports/{layout_id}/runs` (project and organisation): queues the same run (202 + the run).
- `POST /api/v1/report-runs/{id}/again`: queues a fresh run of an expired or failed run's stored request.
- `GET /api/v1/report-runs`, `GET /api/v1/report-runs/{id}`, `GET /api/v1/report-runs/{id}/download`,
  `DELETE /api/v1/report-runs/{id}`: the caller's own background runs; the file is downloadable only by the
  requester, until it expires (`services.report_run_jobs`).

Run-time variables: `variables` is a JSON object `{name: value}` (a query parameter on GET, a field on POST; a
variable left out takes its default). A missing, undeclared or unacceptable value answers 422 with
`detail.code == "variable_values"` and `detail.problems`. `GET .../{layout_id}/variables` returns the run form: each
variable with its default and current options. Values are stored with the run (provenance) and never logged; the
front proxy logs the path only.

`format` is limited by the layout's family (`services.custom_report_run.available_formats`, which reads the
renderer registry, `services.report_render`): 400 otherwise. A table layout's `csv` is a zip when it has
several sheets.
A run over its work, output or time limit answers 413 (408 for time) for the on-screen form and 409 (see above)
for a file, and writes nothing.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime
from typing import Any, Literal, TypeVar
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models.enums import OrgRole
from app.models.generated_report import GeneratedReport
from app.models.organization import Organization
from app.models.project import Project
from app.models.report_layout import ReportLayout, ReportLayoutVersion
from app.models.user import User
from app.schemas.report_layout import ReportVariablesOut
from app.services import custom_report_run, report_layout_scope, report_layouts, report_run_jobs
from app.services.client_date import effective_today
from app.services.custom_report_run import LayoutRun
from app.services.downloads import file_response
from app.services.rbac import check_pat_scope, require_org_role, require_project_view
from app.services.report_framework import ReportOut, to_out
from app.services.report_layout_eval import LayoutLimitError, LayoutTimeoutError
from app.services.report_render import RenderedFile
from app.services.report_variables import VariableValueError, describe_variables, resolve_values

T = TypeVar("T")

project_router = APIRouter(prefix="/api/v1/projects/{project_id}/custom-reports", tags=["custom-reports"])
org_router = APIRouter(prefix="/api/v1/orgs/{organization_id}/custom-reports", tags=["custom-reports"])

CustomReportFormat = Literal["json", "pdf", "docx", "odt", "html", "csv", "xlsx", "ods"]
"""Every format any family offers; `available_formats` narrows it per layout (400)."""
_RESPONSES: dict[int | str, dict[str, Any]] = {
    200: {"content": {"application/pdf": {}, "text/csv": {}, "text/html": {}, "application/zip": {}}},
}


def _current_version(db: Session, layout: ReportLayout) -> ReportLayoutVersion:
    version = report_layouts.get_version(db, layout.id, layout.current_version)
    assert version is not None  # a layout always has its current version
    return version


def _check_format(layout: ReportLayout, version: ReportLayoutVersion, fmt: str) -> None:
    """Raises 400 naming the formats this layout offers when `fmt` is not one of them."""
    allowed = custom_report_run.available_formats(layout.family, version.tree)
    if fmt not in allowed:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"This {layout.family} layout can be produced as: {', '.join(allowed)}.",
        )


ASYNC_REQUIRED = "async_required"
VARIABLE_VALUES = "variable_values"
MAX_VARIABLES_JSON = 20_000


def parse_variables(raw: str | None) -> dict[str, Any] | None:
    """The `variables` query parameter (a JSON object) as a dict; `None` when absent or blank.

    Raises:
        HTTPException: 422 when it is not a JSON object, or is too long.
    """
    if raw is None or not raw.strip():
        return None
    try:
        if len(raw) > MAX_VARIABLES_JSON:
            raise ValueError
        parsed = json.loads(raw)
    except ValueError:
        parsed = None
    if not isinstance(parsed, dict):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "variables must be a JSON object of values by variable name.")
    return parsed


def checked_variables(version: ReportLayoutVersion, supplied: dict[str, Any] | None) -> dict[str, Any]:
    """The values a run will use, resolved now so a bad value fails the request rather than a queued job.

    Raises:
        HTTPException: 422 `variable_values` (see `guard_run`).
    """
    return guard_run(lambda: resolve_values(version.tree.get("variables"), supplied, today=effective_today()))


def guard_run(call: Callable[[], T], *, file_format: bool = False) -> T:
    """Runs `call`, translating the run's refusals into responses (also used by the designer's preview).

    Args:
        call: The run.
        file_format: The run is for a file. A file run over the synchronous limits can be produced in the
            background, so it answers 409 `async_required` instead of 413/408.
    """
    try:
        return call()
    except LayoutLimitError as exc:
        if file_format:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                {
                    "code": ASYNC_REQUIRED,
                    "message": "This report is too big to produce while you wait. Prepare it in the background and "
                    "you will be notified when it is ready.",
                },
            ) from exc
        if isinstance(exc, LayoutTimeoutError):
            raise HTTPException(status.HTTP_408_REQUEST_TIMEOUT, str(exc)) from exc
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, str(exc)) from exc
    except VariableValueError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            {
                "code": VARIABLE_VALUES,
                "message": "Some values for this report's variables are missing or not acceptable.",
                "problems": [{"name": name, "message": message} for name, message in exc.problems],
            },
        ) from exc
    except custom_report_run.ProjectsNotInScopeError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That project is not covered by this report.") from exc
    except custom_report_run.NoProjectsToRunError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except custom_report_run.FanOutTooLargeError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc


def _respond(
    db: Session, user: User, run: LayoutRun, fmt: str, *, include_children: bool = False, requested: list[UUID] | None = None,
) -> Response | ReportOut:
    """Renders `run` as `fmt`, records its provenance and returns it.

    The row is written after rendering succeeds, so a report that could not be produced leaves no record.
    """
    out: ReportOut | None = None
    rendered: RenderedFile | None = None
    if fmt == "json":
        out = to_out(custom_report_run.result_for(run))
    else:
        rendered = custom_report_run.render_file(db, run, fmt)
    custom_report_run.record_run(db, user, run, fmt, include_children=include_children, requested_project_ids=requested)
    db.commit()
    if out is not None:
        return out
    assert rendered is not None
    return file_response(rendered.content, custom_report_run.file_stem(run, rendered.extension), rendered.extension)


@project_router.get("/{layout_id}/run", response_model=ReportOut, responses=_RESPONSES)
def run_project_custom_report(
    project_id: UUID, layout_id: UUID,
    format: CustomReportFormat = Query(
        "json", description="json (default), or pdf, docx, odt, html (document layouts) / csv, xlsx, ods (table layouts).",
    ),
    include_children: bool = Query(False, description="Also read the records of readable child projects."),
    variables: str | None = Query(
        None, description="A JSON object of values for the layout's run-time variables, e.g. {\"categories\": [\"A\"]}.",
    ),
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
) -> Response | ReportOut:
    """Runs a layout the project can reach for this project.

    Raises:
        HTTPException: 404 the project or layout is not reachable (or the project hid it); 400 a format the
            layout cannot produce; 413/408 a run over its limits; 409
            `async_required` a file run over the synchronous limits; 422 `variable_values` a variable value that
            is missing or not acceptable.
    """
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found.")
    scoped = report_layout_scope.reachable_layout(db, project, layout_id)
    if scoped is None or scoped.hidden:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Layout not found.")
    version = _current_version(db, scoped.layout)
    _check_format(scoped.layout, version, format)
    organization = db.get(Organization, project.organization_id)
    assert organization is not None
    supplied = parse_variables(variables)
    run = guard_run(lambda: custom_report_run.run_project_layout(
        db, current_user, project, scoped.layout, version, include_children=include_children, variables=supplied,
    ), file_format=format != "json")
    return _respond(db, current_user, run, format, include_children=include_children)


def _parse_project_ids(raw: str | None) -> list[UUID] | None:
    """The comma-separated `project_ids` as ids; `None` for absent or blank (every readable project).

    Raises:
        HTTPException: 422 a value that is not a UUID.
    """
    if raw is None or not raw.strip():
        return None
    try:
        return [UUID(part.strip()) for part in raw.split(",") if part.strip()]
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "project_ids must be comma-separated project ids.") from exc


@org_router.get("/{layout_id}/run", response_model=ReportOut, responses=_RESPONSES)
def run_org_custom_report(
    organization_id: UUID, layout_id: UUID,
    format: CustomReportFormat = Query(
        "json", description="json (default), or pdf, docx, odt, html (document layouts) / csv, xlsx, ods (table layouts).",
    ),
    project_ids: str | None = Query(
        None, description="Comma-separated projects to include (narrowing only); default every project you can read.",
    ),
    variables: str | None = Query(
        None, description="A JSON object of values for the layout's run-time variables, e.g. {\"categories\": [\"A\"]}.",
    ),
    current_user: User = Depends(require_org_role(*OrgRole)), db: Session = Depends(get_db),
) -> Response | ReportOut:
    """Runs an organisation layout once per project the caller can read (or the selected ones) and merges the results.

    Raises:
        HTTPException: 404 the layout is not the organisation's, a selected project is not one the caller can
            report on, or no project is left; 400 a format the layout cannot produce;
            422 a malformed or oversized selection, or a variable value that is missing or not acceptable (`variable_values`);
            413/408 a run over its limits; 409 `async_required` a file run over the synchronous limits.
    """
    organization = db.get(Organization, organization_id)
    layout = db.get(ReportLayout, layout_id)
    if organization is None or layout is None or layout.organization_id != organization_id or layout.project_id is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Layout not found.")
    version = _current_version(db, layout)
    _check_format(layout, version, format)
    requested = _parse_project_ids(project_ids)
    supplied = parse_variables(variables)
    run = guard_run(lambda: custom_report_run.run_organization_layout(
        db, current_user, organization, layout, version, project_ids=requested, variables=supplied,
    ), file_format=format != "json")
    return _respond(db, current_user, run, format, requested=requested)


@project_router.get("/{layout_id}/variables", response_model=ReportVariablesOut)
def project_report_variables(
    project_id: UUID, layout_id: UUID, current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
) -> ReportVariablesOut:
    """The run form of a layout the project can reach: its variables, defaults and current options.

    Raises:
        HTTPException: 404 the project or layout is not reachable (or the project hid it).
    """
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found.")
    scoped = report_layout_scope.reachable_layout(db, project, layout_id)
    if scoped is None or scoped.hidden:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Layout not found.")
    version = _current_version(db, scoped.layout)
    return ReportVariablesOut.model_validate({
        "variables": describe_variables(db, version.tree.get("variables"), [project.id], today=effective_today()),
    })


@org_router.get("/{layout_id}/variables", response_model=ReportVariablesOut)
def org_report_variables(
    organization_id: UUID, layout_id: UUID,
    project_ids: str | None = Query(None, description="Comma-separated projects the run will cover (default: every project you can read)."),
    current_user: User = Depends(require_org_role(*OrgRole)), db: Session = Depends(get_db),
) -> ReportVariablesOut:
    """The run form of an organisation layout: its variables, defaults and options across the projects the run covers.

    Raises:
        HTTPException: 404 the layout is not the organisation's or a selected project is not one the caller can
            report on; 422 a malformed selection.
    """
    organization = db.get(Organization, organization_id)
    layout = db.get(ReportLayout, layout_id)
    if organization is None or layout is None or layout.organization_id != organization_id or layout.project_id is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Layout not found.")
    version = _current_version(db, layout)
    requested = _parse_project_ids(project_ids)
    readable = custom_report_run.readable_projects(db, current_user, organization=organization, root_project=None, include_children=False)
    scope = [p.id for p in readable]
    if requested is not None:
        if any(pid not in scope for pid in requested):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "That project is not covered by this report.")
        scope = requested
    return ReportVariablesOut.model_validate({
        "variables": describe_variables(
            db, version.tree.get("variables"), scope[: custom_report_run.MAX_FANOUT_PROJECTS], today=effective_today(),
        ),
    })


# --- background runs ---------------------------------------------------------------------------------------------


class ProjectRunRequest(BaseModel):
    """A request to prepare a project-level custom report in the background."""

    format: CustomReportFormat = Field(description="A file format the layout offers (not json).")
    include_children: bool = False
    variables: dict[str, Any] | None = Field(default=None, max_length=50, description="Values for the layout's run-time variables.")


class OrgRunRequest(BaseModel):
    """A request to prepare an organisation-wide custom report in the background."""

    format: CustomReportFormat = Field(description="A file format the layout offers (not json).")
    project_ids: list[UUID] | None = Field(default=None, max_length=custom_report_run.MAX_FANOUT_PROJECTS)
    variables: dict[str, Any] | None = Field(default=None, max_length=50, description="Values for the layout's run-time variables.")


class ReportRunOut(BaseModel):
    """One of the caller's background runs."""

    id: UUID
    organization_id: UUID
    project_id: UUID | None
    scope: str
    layout_name: str
    layout_version: int
    format: str
    status: str
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    expires_at: datetime | None
    output_filename: str | None
    output_size: int | None
    error: str | None

    @classmethod
    def of(cls, row: GeneratedReport) -> ReportRunOut:
        """The API form of a run row."""
        return cls(
            id=row.id, organization_id=row.organization_id, project_id=row.project_id, scope=row.scope,
            layout_name=row.layout_name, layout_version=row.layout_version, format=row.format, status=row.status,
            created_at=row.created_at, started_at=row.started_at, finished_at=row.finished_at,
            expires_at=row.expires_at, output_filename=row.output_filename, output_size=row.output_size, error=row.error,
        )


class ReportRunAgainOut(BaseModel):
    """The fresh run queued by "generate again", and whether the report was edited since the old one."""

    run: ReportRunOut
    definition_changed: bool = Field(description="The layout or pack has a newer version than the run it repeats.")


def _queue(
    db: Session, user: User, organization: Organization, project: Project | None, layout: ReportLayout,
    version: ReportLayoutVersion, fmt: str, *, include_children: bool = False,
    requested: list[UUID] | None = None, variables: dict[str, Any] | None = None,
) -> ReportRunOut:
    """Queues a background run and returns it (the formats were checked by the caller).

    Raises:
        HTTPException: 400 for `json` (the on-screen form has no file), 422 `variable_values`, 429 when the caller
            has too many queued.
    """
    if fmt == "json":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Choose a file format; the on-screen report runs immediately.")
    resolved = checked_variables(version, variables)
    try:
        row = report_run_jobs.enqueue(
            db, user, organization=organization, project=project, layout=layout, version=version, fmt=fmt,
            include_children=include_children, requested_project_ids=requested, variables=resolved,
        )
    except report_run_jobs.TooManyActiveRunsError as exc:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, str(exc)) from exc
    db.commit()
    return ReportRunOut.of(row)


@project_router.post("/{layout_id}/runs", response_model=ReportRunOut, status_code=status.HTTP_202_ACCEPTED)
def queue_project_custom_report(
    project_id: UUID, layout_id: UUID, payload: ProjectRunRequest,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
) -> ReportRunOut:
    """Queues a layout the project can reach to be produced in the background for this project.

    The caller is notified when the file is ready (or could not be produced). The same checks as the
    synchronous run apply now and again when the job runs.

    Raises:
        HTTPException: 404 the project or layout is not reachable; 400 a format the layout cannot produce or
            `json`; 429 too many background runs already queued.
    """
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found.")
    scoped = report_layout_scope.reachable_layout(db, project, layout_id)
    if scoped is None or scoped.hidden:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Layout not found.")
    version = _current_version(db, scoped.layout)
    _check_format(scoped.layout, version, payload.format)
    organization = db.get(Organization, project.organization_id)
    assert organization is not None
    return _queue(
        db, current_user, organization, project, scoped.layout, version, payload.format,
        include_children=payload.include_children, variables=payload.variables,
    )


@org_router.post("/{layout_id}/runs", response_model=ReportRunOut, status_code=status.HTTP_202_ACCEPTED)
def queue_org_custom_report(
    organization_id: UUID, layout_id: UUID, payload: OrgRunRequest,
    current_user: User = Depends(require_org_role(*OrgRole)), db: Session = Depends(get_db),
) -> ReportRunOut:
    """Queues an organisation layout to be produced in the background, once per project the caller can read.

    Raises:
        HTTPException: 404 the layout is not the organisation's; 400 a format the layout cannot produce or `json`;
            429 too many background runs already queued.
    """
    organization = db.get(Organization, organization_id)
    layout = db.get(ReportLayout, layout_id)
    if organization is None or layout is None or layout.organization_id != organization_id or layout.project_id is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Layout not found.")
    version = _current_version(db, layout)
    _check_format(layout, version, payload.format)
    return _queue(
        db, current_user, organization, None, layout, version, payload.format, requested=payload.project_ids,
        variables=payload.variables,
    )


runs_router = APIRouter(prefix="/api/v1/report-runs", tags=["custom-reports"])


def _own_run(db: Session, user: User, run_id: UUID, request: Request) -> GeneratedReport:
    """One of the caller's background runs, or 404 (a run of someone else's looks the same as none)."""
    try:
        row = report_run_jobs.get_for(db, user, run_id)
    except report_run_jobs.RunNotAvailableError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    check_pat_scope(request, row.organization_id)
    return row


@runs_router.get("", response_model=list[ReportRunOut])
def list_report_runs(
    organization_id: UUID | None = Query(None, description="Only runs in this organisation."),
    active: bool = Query(False, description="Only runs that are waiting or being prepared."),
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
) -> list[ReportRunOut]:
    """The caller's own background runs, newest first (nobody else's)."""
    rows = report_run_jobs.list_for(db, current_user, organization_id, active_only=active)
    return [ReportRunOut.of(r) for r in rows]


@runs_router.get("/{run_id}", response_model=ReportRunOut)
def get_report_run(
    run_id: UUID, request: Request, current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
) -> ReportRunOut:
    """One of the caller's background runs (404 for anyone else's)."""
    return ReportRunOut.of(_own_run(db, current_user, run_id, request))


@runs_router.get("/{run_id}/download", responses=_RESPONSES)
def download_report_run(
    run_id: UUID, request: Request, current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
) -> Response:
    """The stored file of a `ready` run, for the person who asked for it, until it expires.

    Raises:
        HTTPException: 404 not the caller's, not ready, expired, or the caller lost access since it was produced.
    """
    _own_run(db, current_user, run_id, request)
    try:
        row, content = report_run_jobs.read_output(db, current_user, run_id)
    except report_run_jobs.RunNotAvailableError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    assert row.output_filename is not None
    stem, _, extension = row.output_filename.rpartition(".")
    return file_response(content, stem, extension)


@runs_router.post("/{run_id}/again", response_model=ReportRunAgainOut, status_code=status.HTTP_202_ACCEPTED)
def run_report_again(
    run_id: UUID, request: Request, current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
) -> ReportRunAgainOut:
    """Queues a fresh run of an expired or failed run's stored request, as the caller now.

    The report's current version runs with today's data and the caller's present access; the old file is never
    reused. The caller is notified when the new file is ready.

    Raises:
        HTTPException: 404 not the caller's run, or the report is gone or no longer reachable; 409 the run is
            waiting, being prepared or still downloadable; 422 the stored values or format no longer fit the report;
            429 too many background runs already queued.
    """
    _own_run(db, current_user, run_id, request)
    try:
        row, changed = report_run_jobs.requeue(db, current_user, run_id)
    except report_run_jobs.RunNotAvailableError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except report_run_jobs.RepeatNotNeededError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except report_run_jobs.RepeatRefusedError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    except report_run_jobs.TooManyActiveRunsError as exc:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, str(exc)) from exc
    db.commit()
    return ReportRunAgainOut(run=ReportRunOut.of(row), definition_changed=changed)


@runs_router.delete("/{run_id}", response_model=ReportRunOut)
def delete_report_run(
    run_id: UUID, request: Request, current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
) -> ReportRunOut:
    """Removes a run's stored file now (or cancels it while queued); the provenance row stays.

    Raises:
        HTTPException: 404 not the caller's; 409 the report is being prepared right now.
    """
    _own_run(db, current_user, run_id, request)
    try:
        row = report_run_jobs.delete_output(db, current_user, run_id)
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return ReportRunOut.of(row)


__all__ = ["guard_run", "org_router", "project_router", "runs_router"]
