"""
Module: routers.report_copy

Copies report layouts, packs, folders and module-report placements from one project to another project of the same
organisation (`services.report_copy`).

- `POST /api/v1/projects/{project_id}/report-copy`: copies into the project in the path (the target); the body names the
  source project and the selection. `dry_run` returns the plan (what would be created, renamed, skipped, or cannot be
  carried) and writes nothing.
- `GET /api/v1/projects/{project_id}/report-copy/targets`: the projects the caller can copy this project's reports into.

Access: **manage report layouts in both projects** (`manage_project_report_layouts`; no server-administrator bypass).
Reading a layout's definition is itself a manage action, so the source is held to the same permission; a caller who
may see the source project but not manage its reports gets 403, one who has no access to it (or names a project of
another organisation, or none) gets 404 and learns nothing about it. Both projects must be unarchived (409). Nothing
is copied that the caller could not already open in the source.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.project import Project
from app.models.user import User
from app.schemas.report_copy import ReportCopyItemOut, ReportCopyOut, ReportCopyRequest, ReportCopyTargetOut
from app.services import report_copy
from app.services.rbac import (
    MANAGE_PROJECT_REPORT_LAYOUTS,
    check_pat_project_scope,
    get_effective_permissions,
    get_effective_project_roles,
    permission_satisfied,
    require_permission,
)

router = APIRouter(prefix="/api/v1/projects/{project_id}/report-copy", tags=["report-copy"])

manage_project = require_permission(MANAGE_PROJECT_REPORT_LAYOUTS, server_admin_bypass=False)

MAX_TARGETS = 500


def _manages(db: Session, user: User, project: Project) -> bool:
    return permission_satisfied(
        get_effective_permissions(db, user.id, organization_id=project.organization_id, project_id=project.id),
        MANAGE_PROJECT_REPORT_LAYOUTS,
    )


def _project_or_404(db: Session, project_id: UUID) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found.")
    return project


def _source_project(db: Session, request: Request, user: User, target: Project, source_id: UUID) -> Project:
    """The project to copy from, after the source gate.

    Raises:
        HTTPException: 404 when it does not exist, is in another organisation or the caller has no access to it;
            403 when the caller may see it but not manage its reports; 409 when it is archived.
    """
    source = db.get(Project, source_id)
    if source is None or source.organization_id != target.organization_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found.")
    check_pat_project_scope(request, source.id)
    if not _manages(db, user, source):
        if get_effective_project_roles(db, user.id, source.id):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient permissions in the source project.")
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found.")
    if source.is_archived:
        raise HTTPException(status.HTTP_409_CONFLICT, "The source project is archived.")
    return source


@router.get("/targets", response_model=list[ReportCopyTargetOut])
def list_copy_targets(
    project_id: UUID, current_user: User = Depends(manage_project), db: Session = Depends(get_db),
) -> list[ReportCopyTargetOut]:
    """The unarchived projects of this project's organisation (not itself) whose reports the caller can manage."""
    source = _project_or_404(db, project_id)
    candidates = db.scalars(
        select(Project)
        .where(Project.organization_id == source.organization_id, Project.id != source.id, Project.is_archived.is_(False))
        .order_by(Project.name).limit(MAX_TARGETS)
    ).all()
    return [
        ReportCopyTargetOut(id=p.id, name=p.name, parent_project_id=p.parent_project_id)
        for p in candidates if _manages(db, current_user, p)
    ]


@router.post("", response_model=ReportCopyOut)
def copy_reports(
    project_id: UUID, body: ReportCopyRequest, request: Request,
    current_user: User = Depends(manage_project), db: Session = Depends(get_db),
) -> ReportCopyOut:
    """Copies the selected reports from the source project into this one (or, with `dry_run`, plans the copy).

    Raises:
        HTTPException: 404 an unknown or inaccessible source, or an item the source does not have; 403 no manage right
            in the source; 409 an archived project; 422 the same project twice or too many items.
    """
    target = _project_or_404(db, project_id)
    if target.is_archived:
        raise HTTPException(status.HTTP_409_CONFLICT, "The project is archived.")
    source = _source_project(db, request, current_user, target, body.source_project_id)
    selection = report_copy.CopySelection(
        layout_ids=tuple(body.layout_ids), pack_ids=tuple(body.pack_ids), folders=tuple(body.folders),
        placement_keys=tuple(body.placement_keys), favourites=body.favourites,
    )
    try:
        run = report_copy.plan_copy if body.dry_run else report_copy.apply_copy
        plan = run(db, source=source, target=target, caller=current_user, selection=selection, on_conflict=body.on_conflict)
    except report_copy.CopyRefusedError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    if not body.dry_run:
        db.commit()
    return ReportCopyOut(
        dry_run=body.dry_run, target_project_id=target.id, warnings=plan.warnings, favourites_carried=plan.favourites_carried,
        items=[
            ReportCopyItemOut(
                kind=i.kind, source_id=i.source_id, name=i.name, origin=i.origin, action=i.action, new_name=i.new_name,
                warnings=i.warnings, new_id=i.new_id,
            )
            for i in plan.items
        ],
    )
