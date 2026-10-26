"""
Module: routers.custom_reports

Runs a custom report layout (`services.custom_report_run`):

- `GET /api/v1/projects/{project_id}/custom-reports/{layout_id}/run?format=json|pdf|docx|csv`: a layout the
  project can reach (its own, an ancestor's or the organisation's, unless the project hid it), for this
  project and, with `include_children`, its readable child projects.
- `GET /api/v1/orgs/{organization_id}/custom-reports/{layout_id}/run?format=...&project_ids=a,b`: an
  organisation layout run once per project the caller can read (or the selected ones) and merged.

Access: running needs only what reading the data needs (D13): membership of the project or organisation;
each record is then shown only if the caller's own project permissions allow it. Neither route needs the
manage-layouts permission. Every run writes a provenance row (`GeneratedReport`); no output is stored.

`format` is limited by the layout's family (`services.custom_report_run.available_formats`): 400 otherwise.
A run over its work, output or time limit answers 413 (408 for time) and writes nothing.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.enums import OrgRole
from app.models.organization import Organization, ReportTemplate
from app.models.project import Project
from app.models.report_layout import ReportLayout, ReportLayoutVersion
from app.models.user import User
from app.services import custom_report_run, report_layout_scope, report_layouts
from app.services.custom_report_run import LayoutRun
from app.services.downloads import file_response, filename_safe
from app.services.rbac import require_org_role, require_project_view
from app.services.report_document import load_report_template, resolve_branding
from app.services.report_docx import render_docx_document
from app.services.report_framework import ReportFormat, ReportOut, to_out
from app.services.report_layout_eval import LayoutLimitError, LayoutTimeoutError
from app.services.report_model import Block
from app.services.report_pdf import render_pdf_document

project_router = APIRouter(prefix="/api/v1/projects/{project_id}/custom-reports", tags=["custom-reports"])
org_router = APIRouter(prefix="/api/v1/orgs/{organization_id}/custom-reports", tags=["custom-reports"])

_RESPONSES: dict[int | str, dict[str, Any]] = {200: {"content": {"application/pdf": {}, "text/csv": {}}}}


def _template(db: Session, organization: Organization, template_id: UUID | None) -> ReportTemplate | None:
    """The requested branding template, `None` when none was asked for.

    Raises:
        HTTPException: 400 when it is not one of the organisation's.
    """
    if template_id is None:
        return None
    template = load_report_template(db, organization.id, template_id)
    if template is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid report_template_id for this organisation.")
    return template


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


def _run(call: Callable[[], LayoutRun]) -> LayoutRun:
    """Runs `call`, translating the run's refusals into responses."""
    try:
        return call()
    except LayoutTimeoutError as exc:
        raise HTTPException(status.HTTP_408_REQUEST_TIMEOUT, str(exc)) from exc
    except LayoutLimitError as exc:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, str(exc)) from exc
    except custom_report_run.ProjectsNotInScopeError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That project is not covered by this report.") from exc
    except custom_report_run.NoProjectsToRunError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except custom_report_run.FanOutTooLargeError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc


def _respond(
    db: Session, user: User, run: LayoutRun, fmt: str, template: ReportTemplate | None, *,
    include_children: bool = False, requested: list[UUID] | None = None,
) -> Response | ReportOut:
    """Renders `run` as `fmt`, records its provenance and returns it.

    The row is written after rendering succeeds, so a report that could not be produced leaves no record.
    """
    out: ReportOut | None = None
    content: tuple[bytes, str] | None = None
    if fmt == "json":
        out = to_out(custom_report_run.result_for(run))
    elif fmt == "csv":
        content = custom_report_run.csv_for(run), "csv"
    else:
        before: list[Block]
        after: list[Block]
        before, after = custom_report_run.content_blocks_for(db, run, template)
        document = custom_report_run.document_for(run, branding=resolve_branding(db, run.organization, template), before=before, after=after)
        content = (render_docx_document(document), "docx") if fmt == "docx" else (render_pdf_document(document), "pdf")
    custom_report_run.record_run(
        db, user, run, fmt, report_template_id=template.id if template else None, include_children=include_children,
        requested_project_ids=requested,
    )
    db.commit()
    if out is not None:
        return out
    assert content is not None
    stem = f"{filename_safe(run.scope_label, fallback='report')}-{filename_safe(run.layout.name, fallback='report')}"
    return file_response(content[0], stem, content[1])


@project_router.get("/{layout_id}/run", response_model=ReportOut, responses=_RESPONSES)
def run_project_custom_report(
    project_id: UUID, layout_id: UUID,
    format: ReportFormat = Query("json", description="json (default), pdf, docx or csv; the layout's family limits it."),
    include_children: bool = Query(False, description="Also read the records of readable child projects."),
    report_template_id: UUID | None = Query(None, description="An organisation report template's branding for the PDF and Word."),
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
) -> Response | ReportOut:
    """Runs a layout the project can reach for this project.

    Raises:
        HTTPException: 404 the project or layout is not reachable (or the project hid it); 400 a format the
            layout cannot produce, or a template of another organisation; 413/408 a run over its limits.
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
    template = _template(db, organization, report_template_id)
    run = _run(lambda: custom_report_run.run_project_layout(
        db, current_user, project, scoped.layout, version, include_children=include_children,
    ))
    return _respond(db, current_user, run, format, template, include_children=include_children)


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
    format: ReportFormat = Query("json", description="json (default), pdf, docx or csv; the layout's family limits it."),
    project_ids: str | None = Query(
        None, description="Comma-separated projects to include (narrowing only); default every project you can read.",
    ),
    report_template_id: UUID | None = Query(None, description="An organisation report template's branding for the PDF and Word."),
    current_user: User = Depends(require_org_role(*OrgRole)), db: Session = Depends(get_db),
) -> Response | ReportOut:
    """Runs an organisation layout once per project the caller can read (or the selected ones) and merges the results.

    Raises:
        HTTPException: 404 the layout is not the organisation's, a selected project is not one the caller can
            report on, or no project is left; 400 a format the layout cannot produce or a foreign template;
            422 a malformed or oversized selection; 413/408 a run over its limits.
    """
    organization = db.get(Organization, organization_id)
    layout = db.get(ReportLayout, layout_id)
    if organization is None or layout is None or layout.organization_id != organization_id or layout.project_id is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Layout not found.")
    version = _current_version(db, layout)
    _check_format(layout, version, format)
    requested = _parse_project_ids(project_ids)
    template = _template(db, organization, report_template_id)
    run = _run(lambda: custom_report_run.run_organization_layout(
        db, current_user, organization, layout, version, project_ids=requested,
    ))
    return _respond(db, current_user, run, format, template, requested=requested)


__all__ = ["org_router", "project_router"]
