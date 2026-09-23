"""
Module: routers.requirements.files

Direct file attachments (C-M-02) and organisation shared-resource links
(C-M-04) on a requirement. Both the upload and link-existing-resource paths
are creation-or-change-request-only once the requirement is approved
(C-G-12) — see `upload_requirement_attachment`'s docstring.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.file import FileAsset, RequirementFile
from app.models.project import Project
from app.models.user import User
from app.routers.requirements.core import _get_requirement_in_project, _require_edit_role
from app.schemas.file import FileAssetOut, LinkResourceRequest
from app.services.audit import log_event
from app.services.files import delete_file, upload_file
from app.services.rbac import require_project_view
from app.services.requirements import get_current_version, is_locked

router = APIRouter(tags=["requirements-files"])


@router.post("/{requirement_id}/files", response_model=FileAssetOut, status_code=status.HTTP_201_CREATED)
async def upload_requirement_attachment(
    project_id: UUID, requirement_id: UUID, file: UploadFile = File(...),
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    """Uploads and attaches a new file to a requirement (C-M-02).

    Governed by the same creation-or-change-request-only rule as every
    other requirement content field once it's locked (C-G-12) — a direct
    attachment is only allowed while the requirement is still unlocked
    (i.e. at/around creation time); once approved, new attachments must go
    through a change request instead (see `decide_change_request`'s
    "attachments" handling). Hardening-review finding: this endpoint
    previously had no lock check at all, unlike every other field, letting
    attachments bypass the change-request-only rule entirely.
    """
    _require_edit_role(db, current_user, project_id)
    requirement = _get_requirement_in_project(db, project_id, requirement_id)
    if is_locked(get_current_version(db, requirement.id)):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This requirement is approved; new attachments must be added via a change request.",
        )
    project = db.get(Project, project_id)
    data = await file.read()
    asset = upload_file(
        db, organization_id=project.organization_id, uploaded_by=current_user.id,
        filename=file.filename or "file", content_type=file.content_type or "application/octet-stream", data=data,
    )
    db.flush()
    db.add(RequirementFile(requirement_id=requirement.id, file_id=asset.id, linked_by=current_user.id, created_at=asset.created_at))
    log_event(db, entity_type="requirement", entity_id=requirement.id, action="file_attached",
              actor_id=current_user.id, project_id=project_id, detail={"filename": asset.filename})
    db.commit()
    db.refresh(asset)
    return asset


@router.post("/{requirement_id}/files/link", response_model=FileAssetOut, status_code=status.HTTP_201_CREATED)
def link_org_resource(
    project_id: UUID, requirement_id: UUID, payload: LinkResourceRequest,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    """Links an organisation shared resource file to a requirement (C-M-04).

    Same creation-or-change-request-only lock rule as
    `upload_requirement_attachment` — see its docstring."""
    _require_edit_role(db, current_user, project_id)
    requirement = _get_requirement_in_project(db, project_id, requirement_id)
    if is_locked(get_current_version(db, requirement.id)):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This requirement is approved; new attachments must be added via a change request.",
        )
    project = db.get(Project, project_id)
    asset = db.get(FileAsset, payload.file_id)
    if asset is None or not asset.is_org_resource or asset.organization_id != project.organization_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "file_id must be a shared resource in this project's organisation.")
    existing = db.scalar(
        select(RequirementFile).where(RequirementFile.requirement_id == requirement.id, RequirementFile.file_id == asset.id)
    )
    if existing is None:
        db.add(RequirementFile(requirement_id=requirement.id, file_id=asset.id, linked_by=current_user.id, created_at=datetime.now(UTC)))
        log_event(db, entity_type="requirement", entity_id=requirement.id, action="file_linked",
                  actor_id=current_user.id, project_id=project_id, detail={"file_id": str(asset.id)})
        db.commit()
    return asset


@router.get("/{requirement_id}/files", response_model=list[FileAssetOut])
def list_requirement_files(
    project_id: UUID, requirement_id: UUID,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    _get_requirement_in_project(db, project_id, requirement_id)
    return db.scalars(
        select(FileAsset)
        .join(RequirementFile, RequirementFile.file_id == FileAsset.id)
        .where(RequirementFile.requirement_id == requirement_id)
    ).all()


@router.delete("/{requirement_id}/files/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
def unlink_requirement_file(
    project_id: UUID, requirement_id: UUID, file_id: UUID,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    """Removes a file from a requirement. Direct (non-shared) uploads are
    deleted outright; shared org resources are only unlinked (C-M-03/C-M-04)."""
    _require_edit_role(db, current_user, project_id)
    requirement = _get_requirement_in_project(db, project_id, requirement_id)
    link = db.scalar(
        select(RequirementFile).where(RequirementFile.requirement_id == requirement.id, RequirementFile.file_id == file_id)
    )
    if link is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not attached to this requirement.")
    asset = db.get(FileAsset, file_id)
    db.delete(link)
    db.flush()
    if asset is not None and not asset.is_org_resource:
        delete_file(db, asset)
    log_event(db, entity_type="requirement", entity_id=requirement.id, action="file_unlinked",
              actor_id=current_user.id, project_id=project_id, detail={"file_id": str(file_id)})
    db.commit()
