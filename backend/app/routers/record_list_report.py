"""
Module: routers.record_list_report

`GET /api/v1/projects/{project_id}/reports/record-list?record_type=<type>&format=json|pdf|docx|html|odt|csv|xlsx|ods`: the table of
any record type that has a `RecordTableProvider` (`services.record_list_report`), narrowed by the same filters as
the type's list and its CSV export (`tag`, `tag_mode`, `project_scope`, and the type's own, listed by
`.../records/{type}/columns`).

Access: a project member holding the type's `view` permission with the type's module on for the project, as for
the CSV export; every file format is audited as an export, `json` (the Reports page's on-screen run) is not.
A parameter the type cannot honour is refused (422) rather than ignored, so a filtered-looking screen never
downloads an unfiltered document. `csv` is the file the export route writes, so it re-imports.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.organization import Organization
from app.models.project import Project
from app.models.user import User
from app.services.downloads import file_response, filename_safe
from app.services.project_scope import ProjectScope
from app.services.rbac import require_project_view
from app.services.record_list_report import MAX_DOCUMENT_ROWS, REPORT_KEY, available_types, collect, default_type
from app.services.record_tables import (
    REPORT_PARAMS,
    audit_export,
    build_table,
    provider_for,
    require_view,
    split_params,
    table_csv,
)
from app.services.report_document import ForeignReportTemplateError, effective_report_template, resolve_branding
from app.services.report_file_names import org_default_stem
from app.services.report_framework import DOCUMENT_FORMATS, ReportFormat, ReportOut, render_result, to_out
from app.services.tags import TagFilter

router = APIRouter(prefix="/api/v1/projects/{project_id}/reports", tags=["reports"])


@router.get(f"/{REPORT_KEY}", response_model=ReportOut, responses={200: {"content": {"application/pdf": {}, "text/csv": {}}}})
def record_list_report(
    project_id: UUID, request: Request,
    record_type: str | None = Query(
        None, description="The record type to list, e.g. `requirement`; default: Requirements, else the first the caller may list.",
    ),
    format: ReportFormat = Query("json", description="json (default), pdf, docx, html, odt, csv, xlsx or ods."),
    report_template_id: UUID | None = Query(None, description="An organisation report template's branding for the PDF and Word."),
    tag_filter: TagFilter = Depends(), project_scope: ProjectScope = Depends(),
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
) -> Response | ReportOut:
    """The list of `record_type` as a report, with the list's own filters.

    Raises:
        HTTPException: 404 the project, the type or its module is not found (or the caller may list no type); 403 no `view` permission; 400 the
            template is not the organisation's; 413 a PDF or Word of more than `MAX_DOCUMENT_ROWS` rows (use
            `csv` or narrow the filters); 422 an unsupported filter.
    """
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found.")
    if record_type is None:
        types = available_types(db, current_user, project)
        if not types:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Record type not found.")
        record_type = default_type(types)
    provider = provider_for(db, project, record_type)
    require_view(db, current_user, project, record_type)
    filters = split_params(provider, request.query_params.multi_items(), also=REPORT_PARAMS)
    organization = db.get(Organization, project.organization_id)
    try:
        template = effective_report_template(db, organization.id, report_template_id)
    except ForeignReportTemplateError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    table = build_table(
        db, current_user, project, record_type, provider, filters=filters, tag_filter=tag_filter, project_scope=project_scope,
    )
    if format in DOCUMENT_FORMATS and len(table.rows) > MAX_DOCUMENT_ROWS:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE,
            f"This list has {len(table.rows)} rows, more than a document is laid out for ({MAX_DOCUMENT_ROWS}). "
            "Narrow the filters or download the CSV.",
        )
    result = collect(project.name, provider.label, table, scope_name=project_scope.name)
    if format == "json":
        return to_out(result)
    stem = f"{filename_safe(project.name, fallback='project')}-{filename_safe(provider.label.lower())}"
    if format == "csv":
        content, ext = table_csv(table), "csv"
    else:
        # A document is named like every catalogue report (`<scope>-<slug>`); the CSV is named like the export it equals.
        rendered = render_result(result, format, branding=resolve_branding(db, organization, template))
        stem = org_default_stem(
            organization, project, title=provider.label, extension=rendered.extension, fallback=f"{stem}-{REPORT_KEY}",
        )
        content, ext = rendered.content, rendered.extension
    audit_export(db, current_user, project, record_type, table, ext)
    return file_response(content, stem, ext)
