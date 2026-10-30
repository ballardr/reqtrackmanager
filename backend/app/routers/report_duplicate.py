"""
Module: routers.report_duplicate

Duplicates one report layout or pack, or starts a layout from a built-in starter (`services.report_duplicate`):

- `POST /api/v1/projects/{project_id}/report-duplicate`: the copy lands in the project (`target: project`) or, with
  `target: organization`, in the organisation (a copy up).
- `POST /api/v1/orgs/{organization_id}/report-duplicate`: the copy lands in the organisation.
- `GET .../report-duplicate/starters`: the built-in starters (their keys feed `kind: starter`).

`dry_run` returns the plan (final name, shadowing, folder, warnings, project pictures that block a copy up) and writes
nothing.

Access: the layout-management permission of the source's scope and of the destination tier (`manage_project_report_layouts`
or `manage_org_report_layouts`, groups included; no server-administrator bypass). Reading a layout's definition is itself a
manage action, so there is no read-only duplicate. A project's copy up also needs the organisation permission (403).
A source the scope cannot reach, or one in another organisation, is a 404. An archived project is 409.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.organization import Organization
from app.models.project import Project
from app.models.user import User
from app.schemas.report_duplicate import ReportDuplicateOut, ReportDuplicateRequest, ReportStarterOut
from app.services import report_duplicate, report_layouts, report_packs
from app.services.rbac import (
    MANAGE_ORG_REPORT_LAYOUTS,
    MANAGE_PROJECT_REPORT_LAYOUTS,
    get_effective_permissions,
    permission_satisfied,
    require_permission,
)

project_router = APIRouter(prefix="/api/v1/projects/{project_id}/report-duplicate", tags=["report-duplicate"])
org_router = APIRouter(prefix="/api/v1/orgs/{organization_id}/report-duplicate", tags=["report-duplicate"])

manage_project = require_permission(MANAGE_PROJECT_REPORT_LAYOUTS, server_admin_bypass=False)
manage_org = require_permission(MANAGE_ORG_REPORT_LAYOUTS, server_admin_bypass=False)


def _starters() -> list[ReportStarterOut]:
    return [
        ReportStarterOut(key=s.key, name=s.name, description=s.description, orientation=s.orientation)
        for s in report_duplicate.starter_sources()
    ]


def _run(
    db: Session, user: User, body: ReportDuplicateRequest, *, organization_id: UUID, project: Project | None,
) -> ReportDuplicateOut:
    """Runs the duplicate and maps the service's refusals to responses; commits on apply."""
    if body.kind == "starter" and not body.starter_key:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Name the starter to start from.")
    try:
        plan = report_duplicate.duplicate(
            db, organization_id=organization_id, project=project, kind=body.kind, source_id=body.source_id,
            starter_key=body.starter_key, target=body.target, name=body.name, caller=user, dry_run=body.dry_run,
        )
    except report_duplicate.DuplicateRefusedError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except (report_layouts.LayoutNameTakenError, report_packs.PackNameTakenError) as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except report_duplicate.DuplicateBlockedError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, {"message": str(exc), "images": exc.images}) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    if not body.dry_run:
        db.commit()
    return ReportDuplicateOut(
        dry_run=body.dry_run, kind=plan.kind, source_name=plan.source_name, origin=plan.origin, name=plan.name,
        suggested_name=plan.suggested_name, name_taken=plan.name_taken, shadows=plan.shadows, folder=plan.folder,
        warnings=plan.warnings, blocked_images=plan.blocked_images, new_id=plan.new_id, target=body.target,
        organization_id=organization_id,
    )


@project_router.get("/starters", response_model=list[ReportStarterOut])
def list_project_starters(project_id: UUID, current_user: User = Depends(manage_project)) -> list[ReportStarterOut]:
    """The built-in starter layouts."""
    return _starters()


@project_router.post("", response_model=ReportDuplicateOut)
def duplicate_project_report(
    project_id: UUID, body: ReportDuplicateRequest,
    current_user: User = Depends(manage_project), db: Session = Depends(get_db),
) -> ReportDuplicateOut:
    """Duplicates a report reachable from the project into the project, or up to the organisation.

    Raises:
        HTTPException: 404 an unknown or unreachable source; 403 a copy up without the organisation right; 409 an archived
            project, a name the destination owns or a project picture that blocks a copy up; 422 a bad name or an
            invalid copy.
    """
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found.")
    if project.is_archived:
        raise HTTPException(status.HTTP_409_CONFLICT, "The project is archived.")
    if body.target == "organization" and not permission_satisfied(
        get_effective_permissions(db, current_user.id, organization_id=project.organization_id), MANAGE_ORG_REPORT_LAYOUTS,
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient permissions in the organisation.")
    return _run(db, current_user, body, organization_id=project.organization_id, project=project)


@org_router.get("/starters", response_model=list[ReportStarterOut])
def list_org_starters(organization_id: UUID, current_user: User = Depends(manage_org)) -> list[ReportStarterOut]:
    """The built-in starter layouts."""
    return _starters()


@org_router.post("", response_model=ReportDuplicateOut)
def duplicate_org_report(
    organization_id: UUID, body: ReportDuplicateRequest,
    current_user: User = Depends(manage_org), db: Session = Depends(get_db),
) -> ReportDuplicateOut:
    """Duplicates an organisation report into the organisation.

    Raises:
        HTTPException: 404 an unknown source; 409 a name the organisation owns; 422 a bad name or an invalid copy.
    """
    if db.get(Organization, organization_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organisation not found.")
    if body.target != "organization":
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "An organisation page copies into the organisation.")
    return _run(db, current_user, body, organization_id=organization_id, project=None)
