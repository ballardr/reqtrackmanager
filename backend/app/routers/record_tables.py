"""
Module: routers.record_tables

The generic table routes of every record type, one set for all of them:

- `GET  /api/v1/projects/{project_id}/records/{record_type}/columns`: the type's columns and import rules.
- `GET  /api/v1/projects/{project_id}/records/{record_type}/export`: the list as CSV, with the list's own filters.
- `POST /api/v1/projects/{project_id}/records/{record_type}/import`: create and update records from the CSV an
  export writes; a preview unless `dry_run=false`.

Access: a project member holding the type's `view` permission, with the type's module on for the project.
An import additionally needs what the type's own create and update endpoints need (checked per row kind in
`services.record_tables`). Which columns may leave or enter is decided in one place
(`services.record_tables.resolve_export_columns`); nothing here knows a record type.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, Response, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.project import Project
from app.models.user import User
from app.modules.registry import RecordColumn
from app.schemas.record_tables import (
    ColumnChangeOut,
    ImportResultOut,
    RecordColumnOut,
    RecordColumnsOut,
    RowResultOut,
)
from app.services.downloads import filename_safe
from app.services.project_scope import ProjectScope
from app.services.rbac import require_project_view
from app.services.record_policy import TagDecision, tag_decisions
from app.services.record_tables import (
    CODE_COLUMN,
    MAX_IMPORT_BYTES,
    MAX_IMPORT_ROWS,
    ImportResult,
    audit_export,
    build_table,
    import_capability,
    may_import,
    provider_for,
    require_view,
    resolve_export_columns,
    run_import,
    split_params,
    table_csv,
)
from app.services.tags import TagFilter

router = APIRouter(prefix="/api/v1/projects/{project_id}/records/{record_type}", tags=["record-tables"])


def _project(db: Session, project_id: UUID) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found.")
    return project


def columns_out(
    label: str, columns: list[RecordColumn], kept: list[RecordColumn], omitted: list[str], decisions: dict[str, TagDecision],
    *, reason: str | None, can_import: bool, filter_params: frozenset[str],
) -> RecordColumnsOut:
    """The columns listing both tiers answer (`RecordColumnsOut`): every column, which the policy lets through, and the import rules."""
    kept_keys = {c.key for c in kept}
    return RecordColumnsOut(
        label=label,
        columns=[
            RecordColumnOut(key=CODE_COLUMN, label="Code", kind="text", importable=False, editable=False, required=False,
                            sensitivity="none", included=True),
            *(
                RecordColumnOut(
                    key=c.key, label=c.label, kind=c.kind, importable=c.importable, editable=c.editable, required=c.required,
                    sensitivity=c.sensitivity, included=c.key in kept_keys,
                    choices=list(c.choices) if c.choices is not None else None,
                )
                for c in columns
            ),
        ],
        omitted_sensitivity=omitted,
        omitted_reasons={tag: decisions[tag].reason or "" for tag in omitted},
        importable=reason is None,
        can_import=reason is None and can_import,
        not_importable_reason=reason,
        filter_params=sorted(filter_params),
        max_rows=MAX_IMPORT_ROWS,
        max_bytes=MAX_IMPORT_BYTES,
    )


def import_result_out(result: ImportResult) -> ImportResultOut:
    """The API shape of an import's preview or outcome (`ImportResultOut`), shared by both tiers' import routes."""
    return ImportResultOut(
        applied=result.applied, created=result.count("create"), updated=result.count("update"),
        unchanged=result.count("unchanged"), failed=result.count("error"),
        rows=[
            RowResultOut(
                row=r.row, action=r.action, code=r.code, message=r.message,
                changes=[ColumnChangeOut(column=c.column, label=c.label, before=c.before, after=c.after) for c in r.changes],
            )
            for r in result.rows
        ],
        ignored_columns=result.ignored_columns, omitted_sensitivity=result.omitted, error_csv=result.error_csv,
    )


@router.get("/columns", response_model=RecordColumnsOut)
def record_columns(
    project_id: UUID, record_type: str, current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
) -> RecordColumnsOut:
    """The columns of `record_type`'s table, which of them the policy lets through, and whether it can be imported."""
    project = _project(db, project_id)
    provider = provider_for(db, project, record_type)
    require_view(db, current_user, project, record_type)
    columns = list(provider.columns(db, project))
    kept, omitted = resolve_export_columns(
        db, current_user, columns, organization_id=project.organization_id, project_id=project.id, purpose="export",
    )
    reason = import_capability(provider, record_type)
    return columns_out(
        provider.label, columns, kept, omitted, tag_decisions(db, current_user, project.organization_id, project.id),
        reason=reason, can_import=reason is None and may_import(db, current_user, project, record_type, provider),
        filter_params=provider.filter_params,
    )


@router.get("/export")
def export_records(
    project_id: UUID, record_type: str, request: Request,
    tag_filter: TagFilter = Depends(), project_scope: ProjectScope = Depends(),
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
) -> Response:
    """The list as a CSV that re-imports (`POST .../import`), narrowed by the list's own filters.

    The query string carries the same filter parameters as the type's list endpoint (`tag`, `tag_mode` and
    `project_scope` for every type; the rest are the type's own, listed by `.../columns`). A parameter the type
    cannot honour is refused rather than ignored, so a filtered-looking screen never downloads everything.

    Raises:
        HTTPException: 404 the type or project is not found or the module is off; 403 no `view` permission;
            422 an unsupported filter.
    """
    project = _project(db, project_id)
    provider = provider_for(db, project, record_type)
    require_view(db, current_user, project, record_type)
    filters = split_params(provider, request.query_params.multi_items())
    table = build_table(
        db, current_user, project, record_type, provider, filters=filters, tag_filter=tag_filter, project_scope=project_scope,
    )
    audit_export(db, current_user, project, record_type, table, "csv")
    stem = f"{filename_safe(project.name, fallback='project')}-{filename_safe(provider.label.lower())}"
    headers = {
        "Content-Disposition": f'attachment; filename="{stem}.csv"',
        "X-Omitted-Sensitivity": ",".join(table.omitted),
        "X-Record-Count": str(len(table.rows)),
    }
    return Response(content=table_csv(table), media_type="text/csv", headers=headers)


@router.post("/import", response_model=ImportResultOut)
async def import_records(
    project_id: UUID, record_type: str, file: UploadFile = File(...),
    dry_run: bool = Query(True, description="Report what would change without writing anything."),
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
) -> ImportResultOut:
    """Creates and updates records from a CSV: a row with a `code` updates that record, a blank `code` creates one.

    A preview (the default) runs every row through the type's own create or update path and rolls it all back,
    so what it reports is what an apply would do. An apply commits the valid rows and returns the failed ones as
    a CSV to fix and upload again.

    Raises:
        HTTPException: 404 the type or project is not found or the module is off; 403 no `view`, create or
            update permission; 413 over 5 MB or 5,000 rows; 422 a malformed file or a type that cannot be imported.
    """
    project = _project(db, project_id)
    provider = provider_for(db, project, record_type)
    require_view(db, current_user, project, record_type)
    if import_capability(provider, record_type) is not None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, import_capability(provider, record_type))
    data = await file.read(MAX_IMPORT_BYTES + 1)
    result = await run_in_threadpool(
        run_import, db, current_user, project, record_type, provider, data, apply=not dry_run,
    )
    return import_result_out(result)
