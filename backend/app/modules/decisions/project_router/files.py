"""
Module: modules.decisions.project_router.files

Direct Decision file attachments: upload/list/unlink. See the package's
own `__init__.py` docstring for the full router-split account.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.file import FileAsset
from app.models.project import Project
from app.models.user import User
from app.modules.decisions.models import DecisionFile
from app.modules.decisions.project_router._shared import _get_decision_in_project, _is_locked, _require_edit_role, _require_view
from app.modules.decisions.service import DECISION_ARTEFACT_TYPE
from app.schemas.file import FileAssetOut
from app.services.audit import log_event
from app.services.files import delete_file, upload_file

router = APIRouter(tags=["decisions-files"])


@router.post("/{decision_id}/files", response_model=FileAssetOut, status_code=status.HTTP_201_CREATED)
async def upload_decision_file(
    project_id: UUID, decision_id: UUID, file: UploadFile = File(...),
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Mirrors `routers.requirements.upload_requirement_attachment`'s
    pattern exactly: `decision_owner`-gated, and rejected once the
    Decision is locked."""
    project = db.get(Project, project_id)
    decision = _get_decision_in_project(db, project_id, decision_id)
    _require_edit_role(db, current_user, project)
    if _is_locked(decision):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "This Decision is approved or superseded; new attachments can no longer be added.",
        )
    data = await file.read()
    asset = upload_file(
        db, organization_id=project.organization_id, uploaded_by=current_user.id,
        filename=file.filename or "file", content_type=file.content_type or "application/octet-stream", data=data,
    )
    db.flush()
    db.add(DecisionFile(decision_id=decision.id, file_id=asset.id, linked_by=current_user.id, created_at=asset.created_at))
    log_event(db, entity_type=DECISION_ARTEFACT_TYPE, entity_id=decision.id, action="file_attached",
              actor_id=current_user.id, project_id=project_id, detail={"filename": asset.filename})
    db.commit()
    db.refresh(asset)
    return asset


@router.get("/{decision_id}/files", response_model=list[FileAssetOut])
def list_decision_files(
    project_id: UUID, decision_id: UUID,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    decision = _get_decision_in_project(db, project_id, decision_id)
    return db.scalars(
        select(FileAsset).join(DecisionFile, DecisionFile.file_id == FileAsset.id).where(DecisionFile.decision_id == decision.id)
    ).all()


@router.delete("/{decision_id}/files/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
def unlink_decision_file(
    project_id: UUID, decision_id: UUID, file_id: UUID,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    project = db.get(Project, project_id)
    decision = _get_decision_in_project(db, project_id, decision_id)
    _require_edit_role(db, current_user, project)
    link = db.scalar(select(DecisionFile).where(DecisionFile.decision_id == decision.id, DecisionFile.file_id == file_id))
    if link is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not attached to this Decision.")
    asset = db.get(FileAsset, file_id)
    db.delete(link)
    db.flush()
    if asset is not None:
        delete_file(db, asset)
    log_event(db, entity_type=DECISION_ARTEFACT_TYPE, entity_id=decision.id, action="file_unlinked",
              actor_id=current_user.id, project_id=project_id, detail={"file_id": str(file_id)})
    db.commit()
