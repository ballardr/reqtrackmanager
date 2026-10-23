"""
Module: routers.org_record_tables

The generic table routes of the records an **organisation** owns (its Strategies, Future States, Guiding
Principles, Personas, Stakeholders and Stakeholder Groups), one set for every such type:

- `GET  /api/v1/orgs/{organization_id}/records/{record_type}/columns`: the type's columns and import rules.
- `GET  /api/v1/orgs/{organization_id}/records/{record_type}/export`: the organisation's own records as CSV, with
  the organisation list's filters.
- `POST /api/v1/orgs/{organization_id}/records/{record_type}/import`: create and update the organisation's own
  records from the CSV an export writes; a preview unless `dry_run=false`.
- `GET  /api/v1/orgs/{organization_id}/reports/record-list`: the same table as a PDF, Word or CSV document.

Access: a member of the organisation with the type's module (and the sub-component its organisation list needs)
on there, answered 404 otherwise. An import additionally needs what the organisation endpoints need to create
and update the type (`OrganizationRecordTable.can_create` / `can_update`). Which columns may leave or enter is the
engine's one rule (`resolve_export_columns`), with the organisation-level `export_personal_data` grant. Nothing
here knows a record type or module.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, Response, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models.organization import Organization
from app.models.user import User
from app.modules.registry import RecordTableProvider, artefact_type_module
from app.routers.record_tables import columns_out, import_result_out
from app.schemas.record_tables import ImportResultOut, RecordColumnsOut
from app.services.downloads import file_response, filename_safe
from app.services.rbac import check_pat_scope, require_org_access_and_module_enabled
from app.services.record_list_report import MAX_DOCUMENT_ROWS, REPORT_KEY, collect
from app.services.record_policy import tag_decisions
from app.services.record_tables import (
    MAX_IMPORT_BYTES,
    audit_export,
    build_org_table,
    import_capability,
    org_may_import,
    org_provider_for,
    require_org_member,
    resolve_export_columns,
    run_org_import,
    split_org_params,
    table_csv,
)
from app.services.report_document import resolve_branding
from app.services.report_framework import ReportFormat, render_docx, render_pdf

router = APIRouter(prefix="/api/v1/orgs/{organization_id}", tags=["record-tables"])


def authorise(
    db: Session, user: User, request: Request, organization_id: UUID, record_type: str,
) -> tuple[Organization, RecordTableProvider]:
    """Resolves the organisation and the type's provider for a caller who may use the organisation's lists.

    Raises:
        HTTPException: 404 when the organisation, the type's organisation tier or its module is absent or off, or the
            caller holds no role in the organisation (all answered alike); 403 for a token scoped to another one.
    """
    organization = db.get(Organization, organization_id)
    if organization is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found.")
    definition = artefact_type_module(record_type)
    if definition is not None:
        require_org_access_and_module_enabled(db, user, organization_id, definition.key, request)
    else:
        check_pat_scope(request, organization_id)
        require_org_member(db, user, organization)
    return organization, org_provider_for(db, organization, record_type)


@router.get("/records/{record_type}/columns", response_model=RecordColumnsOut)
def org_record_columns(
    organization_id: UUID, record_type: str, request: Request,
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
) -> RecordColumnsOut:
    """The columns of the organisation's own `record_type` table, which of them the policy lets through, and whether it can be imported."""
    organization, provider = authorise(db, current_user, request, organization_id, record_type)
    tier = provider.organization
    columns = list(tier.columns(db, organization))
    kept, omitted = resolve_export_columns(db, current_user, columns, organization_id=organization.id, purpose="export")
    reason = import_capability(provider, record_type, organization=True)
    return columns_out(
        provider.label, columns, kept, omitted, tag_decisions(db, current_user, organization.id),
        reason=reason, can_import=reason is None and org_may_import(db, current_user, organization, record_type, tier),
        filter_params=tier.filter_params,
    )


@router.get("/records/{record_type}/export")
def export_org_records(
    organization_id: UUID, record_type: str, request: Request,
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
) -> Response:
    """The organisation's own records as a CSV that re-imports (`POST .../import`), narrowed by the list's filters.

    A parameter the organisation list cannot honour is refused rather than ignored, so a filtered-looking screen
    never downloads everything.

    Raises:
        HTTPException: 404 the type, organisation or module is not found or off; 422 an unsupported filter.
    """
    organization, provider = authorise(db, current_user, request, organization_id, record_type)
    filters = split_org_params(provider, request.query_params.multi_items())
    table = build_org_table(db, current_user, organization, provider, filters=filters)
    audit_export(db, current_user, organization, record_type, table, "csv")
    stem = f"{filename_safe(organization.name, fallback='organisation')}-{filename_safe(provider.label.lower())}"
    headers = {
        "Content-Disposition": f'attachment; filename="{stem}.csv"',
        "X-Omitted-Sensitivity": ",".join(table.omitted),
        "X-Record-Count": str(len(table.rows)),
    }
    return Response(content=table_csv(table), media_type="text/csv", headers=headers)


@router.post("/records/{record_type}/import", response_model=ImportResultOut)
async def import_org_records(
    organization_id: UUID, record_type: str, request: Request, file: UploadFile = File(...),
    dry_run: bool = Query(True, description="Report what would change without writing anything."),
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
) -> ImportResultOut:
    """Creates and updates the organisation's own records from a CSV: a row with a `code` updates that record, a blank one creates.

    A preview (the default) runs every row through the organisation endpoints' own create or update path and rolls
    it all back; an apply commits the valid rows and returns the failed ones as a CSV to fix and upload again. A
    code that names a project's record, or another organisation's, is a row error.

    Raises:
        HTTPException: 404 the type, organisation or module is not found or off; 403 no create or update permission;
            413 over 5 MB or 5,000 rows; 422 a malformed file or a type that cannot be imported.
    """
    organization, provider = authorise(db, current_user, request, organization_id, record_type)
    reason = import_capability(provider, record_type, organization=True)
    if reason is not None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, reason)
    data = await file.read(MAX_IMPORT_BYTES + 1)
    result = await run_in_threadpool(run_org_import, db, current_user, organization, record_type, provider, data, apply=not dry_run)
    return import_result_out(result)


@router.get(f"/reports/{REPORT_KEY}", responses={200: {"content": {"application/pdf": {}, "text/csv": {}}}})
def org_record_list_report(
    organization_id: UUID, request: Request,
    record_type: str = Query(..., description="The record type to list, e.g. `strategy`."),
    format: ReportFormat = Query("pdf", description="pdf, docx or csv."),
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
) -> Response:
    """The organisation's own records of `record_type` as a PDF, Word or CSV document, with the list's filters.

    `csv` is the file the export route writes (it re-imports); every file is audited as an export.

    Raises:
        HTTPException: 404 the type, organisation or module is not found or off; 413 a PDF or Word of more than
            `MAX_DOCUMENT_ROWS` rows (use `csv` or narrow the filters); 422 an unsupported filter or format.
    """
    organization, provider = authorise(db, current_user, request, organization_id, record_type)
    if format == "json":
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Use pdf, docx or csv.")
    filters = split_org_params(provider, [(k, v) for k, v in request.query_params.multi_items() if k != "record_type"])
    table = build_org_table(db, current_user, organization, provider, filters=filters)
    if format in ("pdf", "docx") and len(table.rows) > MAX_DOCUMENT_ROWS:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE,
            f"This list has {len(table.rows)} rows, more than a document is laid out for ({MAX_DOCUMENT_ROWS}). "
            "Narrow the filters or download the CSV.",
        )
    stem = f"{filename_safe(organization.name, fallback='organisation')}-{filename_safe(provider.label.lower())}"
    if format == "csv":
        content, ext = table_csv(table), "csv"
    else:
        result = collect(organization.name, provider.label, table)
        branding = resolve_branding(db, organization, None)
        stem = f"{stem}-{REPORT_KEY}"
        content, ext = (render_docx(result, branding=branding), "docx") if format == "docx" else (render_pdf(result, branding=branding), "pdf")
    audit_export(db, current_user, organization, record_type, table, ext)
    return file_response(content, stem, ext)
