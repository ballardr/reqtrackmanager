"""
Module: routers.report_folders

The folders of the Reports picker for an organisation or a project: list them, add one, rename one and delete one
(`services.report_folder_store`).

Responsibilities:
- `GET .../report-folders` (managers): every folder the scope can file under, with whether it owns it.
- `POST .../report-folders` (managers): add a folder.
- `PATCH .../report-folders` (managers): rename the last level of a folder the scope owns; what is filed in it follows.
- `DELETE .../report-folders?path=` (managers): delete a folder the scope owns; what is filed in it moves up one level.

Design decisions:
- Managing folders takes the same permission as managing report layouts and placements (organisation or project), with
  no server-administrator bypass: it is the same job, arranging what a team is offered.
- A folder path travels in the query string or body, never the URL path, because it contains `/`.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.organization import Organization
from app.models.project import Project
from app.models.user import User
from app.routers.report_layouts import manage_org_layouts, manage_project_layouts
from app.schemas.report_folder import ReportFolderAdd, ReportFolderChangeOut, ReportFolderOut, ReportFolderRename
from app.services import report_folder_store as store

org_router = APIRouter(prefix="/api/v1/orgs/{organization_id}/report-folders", tags=["report-folders"])
project_router = APIRouter(prefix="/api/v1/projects/{project_id}/report-folders", tags=["report-folders"])


def _folders(db: Session, organization_id: UUID, project: Project | None) -> list[ReportFolderOut]:
    return [ReportFolderOut(path=f.path, own=f.own) for f in store.list_folders(db, organization_id, project)]


def _project_or_404(db: Session, project_id: UUID) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found.")
    return project


def _organization_or_404(db: Session, organization_id: UUID) -> None:
    if db.get(Organization, organization_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organisation not found.")


def _refuse(db: Session, exc: store.FolderError, *, not_found: bool = False) -> HTTPException:
    db.rollback()
    return HTTPException(status.HTTP_404_NOT_FOUND if not_found else status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))


def _list(db: Session, organization_id: UUID, project: Project | None) -> list[ReportFolderOut]:
    return _folders(db, organization_id, project)


def _add(db: Session, organization_id: UUID, project: Project | None, body: ReportFolderAdd, user: User) -> list[ReportFolderOut]:
    try:
        store.add_folder(db, organization_id=organization_id, project=project, path=body.path, actor_id=user.id)
    except store.FolderError as exc:
        raise _refuse(db, exc) from exc
    db.commit()
    return _folders(db, organization_id, project)


def _rename(db: Session, organization_id: UUID, project: Project | None, body: ReportFolderRename, user: User) -> ReportFolderChangeOut:
    try:
        path, change = store.rename_folder(
            db, organization_id=organization_id, project=project, path=body.path, name=body.name, actor_id=user.id,
        )
    except store.FolderError as exc:
        raise _refuse(db, exc, not_found=isinstance(exc, store.FolderNotOwned)) from exc
    db.commit()
    return ReportFolderChangeOut(
        folders=_folders(db, organization_id, project), path=path, layouts=change.layouts, packs=change.packs,
        placements=change.placements,
    )


def _delete(db: Session, organization_id: UUID, project: Project | None, path: str, user: User) -> ReportFolderChangeOut:
    try:
        change = store.delete_folder(db, organization_id=organization_id, project=project, path=path, actor_id=user.id)
    except store.FolderError as exc:
        raise _refuse(db, exc, not_found=isinstance(exc, store.FolderNotOwned)) from exc
    db.commit()
    return ReportFolderChangeOut(
        folders=_folders(db, organization_id, project), layouts=change.layouts, packs=change.packs, placements=change.placements,
    )


@org_router.get("", response_model=list[ReportFolderOut])
def list_org_folders(
    organization_id: UUID, current_user: User = Depends(manage_org_layouts), db: Session = Depends(get_db),
) -> list[ReportFolderOut]:
    """The folders the organisation's reports can be filed under."""
    _organization_or_404(db, organization_id)
    return _list(db, organization_id, None)


@org_router.post("", response_model=list[ReportFolderOut], status_code=status.HTTP_201_CREATED)
def add_org_folder(
    organization_id: UUID, body: ReportFolderAdd, current_user: User = Depends(manage_org_layouts), db: Session = Depends(get_db),
) -> list[ReportFolderOut]:
    """Adds a folder to the organisation; answers the refreshed list.

    Raises:
        HTTPException: 422 an empty, unusable or duplicate folder.
    """
    _organization_or_404(db, organization_id)
    return _add(db, organization_id, None, body, current_user)


@org_router.patch("", response_model=ReportFolderChangeOut)
def rename_org_folder(
    organization_id: UUID, body: ReportFolderRename, current_user: User = Depends(manage_org_layouts), db: Session = Depends(get_db),
) -> ReportFolderChangeOut:
    """Renames an organisation folder; what is filed in it follows.

    Raises:
        HTTPException: 404 a folder the organisation does not own; 422 an unusable or duplicate name.
    """
    _organization_or_404(db, organization_id)
    return _rename(db, organization_id, None, body, current_user)


@org_router.delete("", response_model=ReportFolderChangeOut)
def delete_org_folder(
    organization_id: UUID, path: str = Query(min_length=1, max_length=160),
    current_user: User = Depends(manage_org_layouts), db: Session = Depends(get_db),
) -> ReportFolderChangeOut:
    """Deletes an organisation folder; what is filed in it moves up one level.

    Raises:
        HTTPException: 404 a folder the organisation does not own.
    """
    _organization_or_404(db, organization_id)
    return _delete(db, organization_id, None, path, current_user)


@project_router.get("", response_model=list[ReportFolderOut])
def list_project_folders(
    project_id: UUID, current_user: User = Depends(manage_project_layouts), db: Session = Depends(get_db),
) -> list[ReportFolderOut]:
    """The folders the project's reports can be filed under (its own, its ancestors', the organisation's)."""
    project = _project_or_404(db, project_id)
    return _list(db, project.organization_id, project)


@project_router.post("", response_model=list[ReportFolderOut], status_code=status.HTTP_201_CREATED)
def add_project_folder(
    project_id: UUID, body: ReportFolderAdd, current_user: User = Depends(manage_project_layouts), db: Session = Depends(get_db),
) -> list[ReportFolderOut]:
    """Adds a folder to the project; answers the refreshed list.

    Raises:
        HTTPException: 422 an empty, unusable or duplicate folder.
    """
    project = _project_or_404(db, project_id)
    return _add(db, project.organization_id, project, body, current_user)


@project_router.patch("", response_model=ReportFolderChangeOut)
def rename_project_folder(
    project_id: UUID, body: ReportFolderRename, current_user: User = Depends(manage_project_layouts), db: Session = Depends(get_db),
) -> ReportFolderChangeOut:
    """Renames a project folder; what the project filed in it follows.

    Raises:
        HTTPException: 404 a folder the project does not own; 422 an unusable or duplicate name.
    """
    project = _project_or_404(db, project_id)
    return _rename(db, project.organization_id, project, body, current_user)


@project_router.delete("", response_model=ReportFolderChangeOut)
def delete_project_folder(
    project_id: UUID, path: str = Query(min_length=1, max_length=160),
    current_user: User = Depends(manage_project_layouts), db: Session = Depends(get_db),
) -> ReportFolderChangeOut:
    """Deletes a project folder; what the project filed in it moves up one level.

    Raises:
        HTTPException: 404 a folder the project does not own.
    """
    project = _project_or_404(db, project_id)
    return _delete(db, project.organization_id, project, path, current_user)
