"""
Module: routers.report_exchange

Exports report layouts and packs as a `.zip` file and imports such a file (`services.report_exchange`), for a project
or for the organisation.

- `POST /api/v1/projects/{project_id}/report-file/export` and `POST /api/v1/orgs/{organization_id}/report-file/export`:
  the file for the chosen layouts and packs (a POST so a long selection never travels in a URL).
- `POST .../report-file/import?dry_run=true|false`: a multipart upload (`file`, `on_conflict`, `folder`); a preview by
  default, nothing is written until `dry_run=false`.

Access: the layout-management permission of the tier (`manage_project_report_layouts` or `manage_org_report_layouts`,
groups included; no server-administrator bypass), for export as well as import, because reading a layout's definition
is itself a manage action. A layout or pack the tier cannot reach is a 404. An archived project refuses an import (409).
The file is untrusted: size, entry and picture limits are enforced before anything is stored (413/400). The uploaded
text is never logged; the audit events carry counts only.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.organization import Organization
from app.models.project import Project
from app.models.report_layout import ReportLayout
from app.models.report_pack import ReportPack
from app.models.user import User
from app.schemas.report_exchange import ReportFileExportRequest, ReportFileImportOut, ReportFileItemOut
from app.services import report_exchange, report_layout_scope, report_pack_scope
from app.services.audit import log_event
from app.services.bundle_common import bundle_size, iter_bundle_file
from app.services.downloads import content_disposition
from app.services.rbac import MANAGE_ORG_REPORT_LAYOUTS, MANAGE_PROJECT_REPORT_LAYOUTS, require_permission
from app.services.report_file_names import clean_filename
from app.services.report_folders import clean_folder

project_router = APIRouter(prefix="/api/v1/projects/{project_id}/report-file", tags=["report-file"])
org_router = APIRouter(prefix="/api/v1/orgs/{organization_id}/report-file", tags=["report-file"])

manage_project = require_permission(MANAGE_PROJECT_REPORT_LAYOUTS, server_admin_bypass=False)
manage_org = require_permission(MANAGE_ORG_REPORT_LAYOUTS, server_admin_bypass=False)


def _selection(
    db: Session, body: ReportFileExportRequest, layouts: dict[UUID, ReportLayout], packs: dict[UUID, ReportPack],
) -> tuple[list[ReportLayout], list[ReportPack]]:
    """The chosen rows, in request order.

    Raises:
        HTTPException: 422 nothing chosen; 404 a layout or pack the tier cannot reach (or has hidden).
    """
    if not body.layout_ids and not body.pack_ids:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Choose at least one layout or pack to export.")
    try:
        return [layouts[i] for i in dict.fromkeys(body.layout_ids)], [packs[i] for i in dict.fromkeys(body.pack_ids)]
    except KeyError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "A chosen report is not available here.") from None


def _export(
    db: Session, user: User, body: ReportFileExportRequest, *, organization_id: UUID, project: Project | None,
    layouts: dict[UUID, ReportLayout], packs: dict[UUID, ReportPack], label: str,
) -> Response:
    chosen_layouts, chosen_packs = _selection(db, body, layouts, packs)
    result = report_exchange.build_export(
        db, organization_id=organization_id, project=project, layouts=chosen_layouts, packs=chosen_packs,
        include_history=body.include_history, include_pack_layouts=body.include_pack_layouts, exported_by=user,
    )
    log_event(
        db, entity_type="project" if project is not None else "organization", entity_id=project.id if project else organization_id,
        action="report_file_exported", actor_id=user.id, organization_id=organization_id,
        project_id=project.id if project else None,
        detail={"layouts": result.layouts, "packs": result.packs, "pictures": result.pictures, "history": body.include_history},
    )
    db.commit()
    only = chosen_layouts[0].name if len(chosen_layouts) == 1 and not chosen_packs else (
        chosen_packs[0].name if len(chosen_packs) == 1 and not chosen_layouts else f"{label} reports"
    )
    headers = {
        "Content-Disposition": content_disposition("attachment", f"{clean_filename(only)}.zip", fallback="reports.zip"),
        "Content-Length": str(bundle_size(result.file)),
    }
    if result.left_out:
        headers["X-Report-File-Left-Out"] = str(len(result.left_out))
    return StreamingResponse(iter_bundle_file(result.file), media_type="application/zip", headers=headers)


async def _import(
    db: Session, user: User, file: UploadFile, *, organization_id: UUID, project: Project | None, dry_run: bool,
    on_conflict: Literal["rename", "skip"], folder: str,
) -> ReportFileImportOut:
    try:
        tidy = clean_folder(folder) if folder.strip() else None
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    data = await file.read(report_exchange.MAX_FILE_BYTES + 1)
    try:
        parsed = await run_in_threadpool(report_exchange.read_file_bytes, data)
    except report_exchange.ReportFileError as exc:
        code = status.HTTP_413_CONTENT_TOO_LARGE if exc.too_large else status.HTTP_400_BAD_REQUEST
        raise HTTPException(code, str(exc)) from exc
    if dry_run:
        plan = report_exchange.plan_import(db, parsed, organization_id=organization_id, project=project, on_conflict=on_conflict)
    else:
        plan = await run_in_threadpool(
            report_exchange.apply_import, db, parsed, organization_id=organization_id, project=project, actor=user,
            on_conflict=on_conflict, folder=tidy,
        )
        db.commit()
    return ReportFileImportOut(
        dry_run=dry_run, pictures=plan.pictures, warnings=plan.warnings,
        items=[
            ReportFileItemOut(
                kind=i.kind, name=i.name, new_name=i.new_name, action=i.action, versions=i.versions, warnings=i.warnings,
                new_id=i.new_id,
            )
            for i in plan.items
        ],
    )


def _project(db: Session, project_id: UUID) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found.")
    return project


def _organization(db: Session, organization_id: UUID) -> Organization:
    organization = db.get(Organization, organization_id)
    if organization is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organisation not found.")
    return organization


@project_router.post("/export", responses={200: {"content": {"application/zip": {}}}})
def export_project_reports(
    project_id: UUID, body: ReportFileExportRequest, current_user: User = Depends(manage_project), db: Session = Depends(get_db),
) -> Response:
    """The chosen layouts and packs reachable from the project as a report file.

    Raises:
        HTTPException: 404 a report the project cannot reach; 422 nothing chosen.
    """
    project = _project(db, project_id)
    layouts = {s.layout.id: s.layout for s in report_layout_scope.resolve_project_layouts(db, project) if not s.hidden}
    packs = {s.pack.id: s.pack for s in report_pack_scope.resolve_project_packs(db, project) if not s.hidden}
    return _export(
        db, current_user, body, organization_id=project.organization_id, project=project, layouts=layouts, packs=packs,
        label=project.name,
    )


@project_router.post("/import", response_model=ReportFileImportOut)
async def import_project_reports(
    project_id: UUID, file: UploadFile = File(...), on_conflict: Literal["rename", "skip"] = Form("rename"), folder: str = Form(""),
    dry_run: bool = Query(True, description="Preview only: nothing is written."),
    current_user: User = Depends(manage_project), db: Session = Depends(get_db),
) -> ReportFileImportOut:
    """Previews or applies a report file as this project's own layouts and packs.

    Raises:
        HTTPException: 400 not a report file; 413 over a limit; 409 an archived project; 422 a bad option.
    """
    project = _project(db, project_id)
    if project.is_archived:
        raise HTTPException(status.HTTP_409_CONFLICT, "The project is archived.")
    return await _import(
        db, current_user, file, organization_id=project.organization_id, project=project, dry_run=dry_run,
        on_conflict=on_conflict, folder=folder,
    )


@org_router.post("/export", responses={200: {"content": {"application/zip": {}}}})
def export_org_reports(
    organization_id: UUID, body: ReportFileExportRequest, current_user: User = Depends(manage_org), db: Session = Depends(get_db),
) -> Response:
    """The chosen organisation layouts and packs as a report file.

    Raises:
        HTTPException: 404 a report the organisation does not own; 422 nothing chosen.
    """
    organization = _organization(db, organization_id)
    layouts = {lay.id: lay for lay in report_layout_scope.list_org_layouts(db, organization_id)}
    packs = {p.id: p for p in report_pack_scope.list_org_packs(db, organization_id)}
    return _export(
        db, current_user, body, organization_id=organization_id, project=None, layouts=layouts, packs=packs,
        label=organization.name,
    )


@org_router.post("/import", response_model=ReportFileImportOut)
async def import_org_reports(
    organization_id: UUID, file: UploadFile = File(...), on_conflict: Literal["rename", "skip"] = Form("rename"), folder: str = Form(""),
    dry_run: bool = Query(True, description="Preview only: nothing is written."),
    current_user: User = Depends(manage_org), db: Session = Depends(get_db),
) -> ReportFileImportOut:
    """Previews or applies a report file as the organisation's own layouts and packs.

    Raises:
        HTTPException: 400 not a report file; 413 over a limit; 422 a bad option.
    """
    _organization(db, organization_id)
    return await _import(
        db, current_user, file, organization_id=organization_id, project=None, dry_run=dry_run,
        on_conflict=on_conflict, folder=folder,
    )


__all__ = ["org_router", "project_router"]
