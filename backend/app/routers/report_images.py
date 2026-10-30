"""
Module: routers.report_images

The picture libraries a report layout's image block draws from (`services.report_images`):

- Organisation: `/api/v1/orgs/{organization_id}/report-images` (list with the upload size limit, upload, delete);
  organisation layouts may use these only.
- Project: `/api/v1/projects/{project_id}/report-images`; a project layout may use the project's own pictures and the
  organisation's. The project's list shows both, marking which the project owns (only those can be deleted here).

Access: the matching layout-manage permission (`manage_org_report_layouts`, `manage_project_report_layouts`), the
same as for the layouts themselves; a server administrator holds no data access inside an organisation. Upload and
delete are audited (identifiers only). The bytes are read back through `GET /files/{id}`, whose own gate admits
the organisation's members to an organisation image and the project's members to a project image.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.file import RequirementFile
from app.models.project import Project
from app.models.user import User
from app.routers.report_layouts import manage_org_layouts, manage_project_layouts
from app.schemas.report_image import ReportImageLibraryOut, ReportImageOut
from app.services import report_images
from app.services.audit import log_event

org_router = APIRouter(prefix="/api/v1/orgs/{organization_id}/report-images", tags=["report-images"])
project_router = APIRouter(prefix="/api/v1/projects/{project_id}/report-images", tags=["report-images"])


def _out(item: report_images.LibraryImage, own_project: UUID | None) -> ReportImageOut:
    """One library entry; `own_project` is the project whose list this is (`None` for the organisation's)."""
    asset = item.asset
    owned = asset.project_id == own_project if own_project is not None else asset.is_org_resource
    return ReportImageOut(
        id=asset.id, filename=asset.filename, content_type=asset.content_type, size_bytes=asset.size_bytes, tier=item.tier,  # type: ignore[arg-type]
        owned=owned, used_by=item.used_by, in_older_versions=item.in_older_versions, created_at=asset.created_at,
    )


async def _upload(
    db: Session, user: User, organization_id: UUID, project_id: UUID | None, file: UploadFile,
) -> ReportImageOut:
    data = await file.read()
    try:
        asset = report_images.upload_library_image(
            db, organization_id=organization_id, project_id=project_id, uploaded_by=user.id,
            filename=file.filename or "image", data=data,
        )
    except report_images.ImageRejectedError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    db.flush()
    log_event(
        db, entity_type="file_asset", entity_id=asset.id, action="uploaded", actor_id=user.id,
        organization_id=organization_id, project_id=project_id, detail={"purpose": "report_image"},
    )
    db.commit()
    db.refresh(asset)
    return _out(report_images.LibraryImage(asset, "project" if project_id else "organisation", []), project_id)


def _delete(db: Session, user: User, organization_id: UUID, project_id: UUID | None, file_id: UUID) -> None:
    asset = report_images.library_asset(db, organization_id, project_id, file_id)
    if asset is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Image not found.")
    # An organisation image may also be linked to requirements as a shared resource: those links go with it.
    db.execute(delete(RequirementFile).where(RequirementFile.file_id == asset.id))
    report_images.delete_library_image(db, asset)
    log_event(
        db, entity_type="file_asset", entity_id=file_id, action="deleted", actor_id=user.id,
        organization_id=organization_id, project_id=project_id, detail={"purpose": "report_image"},
    )
    db.commit()


def _listing(db: Session, organization_id: UUID, project_id: UUID | None) -> ReportImageLibraryOut:
    return ReportImageLibraryOut(
        images=[_out(i, project_id) for i in report_images.list_library(db, organization_id, project_id)],
        max_image_bytes=report_images.max_image_bytes(),
    )


@org_router.get("", response_model=ReportImageLibraryOut)
def list_org_images(
    organization_id: UUID, current_user: User = Depends(manage_org_layouts), db: Session = Depends(get_db),
) -> ReportImageLibraryOut:
    """The organisation's pictures, newest first, each with the layouts that use it, and the upload size limit."""
    return _listing(db, organization_id, None)


@org_router.post("", response_model=ReportImageOut, status_code=status.HTTP_201_CREATED)
async def upload_org_image(
    organization_id: UUID, file: UploadFile = File(...), current_user: User = Depends(manage_org_layouts),
    db: Session = Depends(get_db),
) -> ReportImageOut:
    """Adds a picture to the organisation's library (every project's layouts can then use it)."""
    return await _upload(db, current_user, organization_id, None, file)


@org_router.delete("/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_org_image(
    organization_id: UUID, file_id: UUID, current_user: User = Depends(manage_org_layouts), db: Session = Depends(get_db),
) -> None:
    """Deletes an organisation picture; layouts that used it skip it with a warning."""
    _delete(db, current_user, organization_id, None, file_id)


def _project(db: Session, project_id: UUID) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found.")
    return project


@project_router.get("", response_model=ReportImageLibraryOut)
def list_project_images(
    project_id: UUID, current_user: User = Depends(manage_project_layouts), db: Session = Depends(get_db),
) -> ReportImageLibraryOut:
    """The project's own pictures and the organisation's, newest first, each with the layouts that use it, and the size limit."""
    return _listing(db, _project(db, project_id).organization_id, project_id)


@project_router.post("", response_model=ReportImageOut, status_code=status.HTTP_201_CREATED)
async def upload_project_image(
    project_id: UUID, file: UploadFile = File(...), current_user: User = Depends(manage_project_layouts),
    db: Session = Depends(get_db),
) -> ReportImageOut:
    """Adds a picture to this project's library (only this project's layouts can use it)."""
    return await _upload(db, current_user, _project(db, project_id).organization_id, project_id, file)


@project_router.delete("/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project_image(
    project_id: UUID, file_id: UUID, current_user: User = Depends(manage_project_layouts), db: Session = Depends(get_db),
) -> None:
    """Deletes one of this project's pictures (an organisation picture is deleted from the organisation's library)."""
    _delete(db, current_user, _project(db, project_id).organization_id, project_id, file_id)


__all__ = ["org_router", "project_router"]
