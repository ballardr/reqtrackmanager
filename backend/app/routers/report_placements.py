"""
Module: routers.report_placements

Where each report appears in the Reports picker, for an organisation or a project: the folder it is filed under and,
for a module report, whether it is shown (`services.report_placements`).

Responsibilities:
- `GET .../report-placements` (managers): every report the scope can place, with its default folder, this scope's own
  override, the effective folder and which tier set it, and whether it is hidden: hidden ones included so they can be
  restored.
- `PUT .../report-placements` (managers): set or clear this scope's override for one report.
- `GET .../report-placements/resolved` (any member): the effective folder and hidden flag by report key, for the
  entries the picker builds itself (the requirements report, packs).

Design decisions:
- Managing placements takes the same permission as managing report layouts (organisation or project), since it is
  the same job: arranging what a team is offered. Neither bypasses for a server administrator.
- A placement tidies the picker, it does not restrict a report: see `services.report_placements`.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.enums import OrgRole
from app.models.organization import Organization
from app.models.project import Project
from app.models.report_placement import ReportPlacement
from app.models.user import User
from app.schemas.report_placement import ReportPlacementOut, ReportPlacementResolvedOut, ReportPlacementSet
from app.services import report_placements
from app.services.rbac import (
    MANAGE_ORG_REPORT_LAYOUTS,
    MANAGE_PROJECT_REPORT_LAYOUTS,
    require_org_role,
    require_permission,
    require_project_view,
)
from app.services.report_placements import Candidate, Resolved

manage_org = require_permission(MANAGE_ORG_REPORT_LAYOUTS, server_admin_bypass=False)
manage_project = require_permission(MANAGE_PROJECT_REPORT_LAYOUTS, server_admin_bypass=False)

org_router = APIRouter(prefix="/api/v1/orgs/{organization_id}/report-placements", tags=["report-placements"])
project_router = APIRouter(prefix="/api/v1/projects/{project_id}/report-placements", tags=["report-placements"])


def _own_rows(db: Session, organization_id: UUID, project_id: UUID | None) -> dict[str, ReportPlacement]:
    where = ReportPlacement.project_id.is_(None) if project_id is None else ReportPlacement.project_id == project_id
    return {
        r.report_key: r
        for r in db.scalars(select(ReportPlacement).where(ReportPlacement.organization_id == organization_id, where))
    }


def _out(
    candidates: list[Candidate], resolved: dict[str, Resolved], own: dict[str, ReportPlacement],
) -> list[ReportPlacementOut]:
    out = []
    for c in candidates:
        placed = resolved.get(c.key, Resolved())
        mine = own.get(c.key)
        out.append(ReportPlacementOut(
            report_key=c.key, title=c.title, description=c.description, kind=c.kind, group=c.group,
            default_folder=c.default_folder, folder=placed.folder if placed.folder is not None else c.default_folder,
            folder_from=placed.folder_from, own_folder=mine.folder if mine else None, hidden=placed.hidden,
            hidden_from=placed.hidden_from, own_hidden=mine.hidden if mine else None,
            can_hide=report_placements.is_hideable(c.key),
        ))
    return out


def _apply(
    db: Session, body: ReportPlacementSet, *, user: User, organization_id: UUID, project_id: UUID | None, valid_keys: set[str],
) -> None:
    own = _own_rows(db, organization_id, project_id).get(body.report_key)
    fields = body.model_fields_set
    folder = body.folder if "folder" in fields else (own.folder if own else None)
    hidden = body.hidden if "hidden" in fields else (own.hidden if own else None)
    try:
        report_placements.set_placement(
            db, organization_id=organization_id, project_id=project_id, key=body.report_key, folder=folder, hidden=hidden,
            valid_keys=valid_keys, actor_id=user.id,
        )
    except report_placements.PlacementError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    db.commit()


def _project_or_404(db: Session, project_id: UUID) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found.")
    return project


def _organization_or_404(db: Session, organization_id: UUID) -> Organization:
    organization = db.get(Organization, organization_id)
    if organization is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organisation not found.")
    return organization


@org_router.get("", response_model=list[ReportPlacementOut])
def list_org_placements(
    organization_id: UUID, current_user: User = Depends(manage_org), db: Session = Depends(get_db),
) -> list[ReportPlacementOut]:
    """Every report the organisation's overview can list for the caller, with its placement."""
    _organization_or_404(db, organization_id)
    return _out(
        report_placements.organization_candidates(db, current_user, organization_id),
        report_placements.resolve_for_organization(db, organization_id), _own_rows(db, organization_id, None),
    )


@org_router.put("", response_model=list[ReportPlacementOut])
def set_org_placement(
    organization_id: UUID, body: ReportPlacementSet, current_user: User = Depends(manage_org), db: Session = Depends(get_db),
) -> list[ReportPlacementOut]:
    """Sets (or clears) the organisation's folder and/or visibility for one report; answers the refreshed list.

    Raises:
        HTTPException: 422 an unknown report, a hide of a layout or pack, or a bad folder.
    """
    _organization_or_404(db, organization_id)
    candidates = report_placements.organization_candidates(db, current_user, organization_id)
    _apply(
        db, body, user=current_user, organization_id=organization_id, project_id=None, valid_keys={c.key for c in candidates},
    )
    return _out(
        candidates, report_placements.resolve_for_organization(db, organization_id), _own_rows(db, organization_id, None),
    )


@org_router.get("/resolved", response_model=list[ReportPlacementResolvedOut])
def resolved_org_placements(
    organization_id: UUID, current_user: User = Depends(require_org_role(*OrgRole)), db: Session = Depends(get_db),
) -> list[ReportPlacementResolvedOut]:
    """The effective folder override and hidden flag by report key (only keys with a placement)."""
    return [
        ReportPlacementResolvedOut(report_key=k, folder=v.folder, hidden=v.hidden)
        for k, v in report_placements.resolve_for_organization(db, organization_id).items()
    ]


@project_router.get("", response_model=list[ReportPlacementOut])
def list_project_placements(
    project_id: UUID, current_user: User = Depends(manage_project), db: Session = Depends(get_db),
) -> list[ReportPlacementOut]:
    """Every report the project's picker can list, with its placement as this project sees it."""
    project = _project_or_404(db, project_id)
    return _out(
        report_placements.project_candidates(db, current_user, project),
        report_placements.resolve_for_project(db, project), _own_rows(db, project.organization_id, project.id),
    )


@project_router.put("", response_model=list[ReportPlacementOut])
def set_project_placement(
    project_id: UUID, body: ReportPlacementSet, current_user: User = Depends(manage_project), db: Session = Depends(get_db),
) -> list[ReportPlacementOut]:
    """Sets (or clears) this project's folder and/or visibility for one report; answers the refreshed list.

    Raises:
        HTTPException: 422 an unknown report, a hide of a layout or pack, or a bad folder.
    """
    project = _project_or_404(db, project_id)
    candidates = report_placements.project_candidates(db, current_user, project)
    _apply(
        db, body, user=current_user, organization_id=project.organization_id, project_id=project.id,
        valid_keys={c.key for c in candidates},
    )
    return _out(
        candidates, report_placements.resolve_for_project(db, project), _own_rows(db, project.organization_id, project.id),
    )


@project_router.get("/resolved", response_model=list[ReportPlacementResolvedOut])
def resolved_project_placements(
    project_id: UUID, current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
) -> list[ReportPlacementResolvedOut]:
    """The effective folder override and hidden flag by report key (only keys with a placement)."""
    project = _project_or_404(db, project_id)
    return [
        ReportPlacementResolvedOut(report_key=k, folder=v.folder, hidden=v.hidden)
        for k, v in report_placements.resolve_for_project(db, project).items()
    ]
