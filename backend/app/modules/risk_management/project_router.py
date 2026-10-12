"""
Module: modules.risk_management.project_router

Project-scoped Risk API (Phase 1), mounted at
`/api/v1/projects/{project_id}/modules/risk_management`: Risk
CRUD/archive/versions/comments/files and the project's Risk type vocabulary
(effective list plus rename/reorder/disable/add).

RBAC: sub-component enablement and project membership to view; any project member
may propose (create) a risk; `_shared.require_risk_manage` (project Risk Manager
role or FGAC grant) to edit, archive, attach evidence or change the project's
types. Lifecycle transitions, links and reviews are later phases. A risk's files
resolve through `service.resolve_risk_file_project_id`.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.project import Project
from app.models.user import User
from app.modules.risk_management import _shared as sh
from app.modules.risk_management.models import ProjectRiskType, Risk
from app.modules.risk_management.ratings import load_rating_context
from app.modules.risk_management.schemas import (
    RiskCommentCreate,
    RiskCommentOut,
    RiskCommentUpdate,
    RiskCreate,
    RiskOut,
    RiskUpdate,
    RiskVersionOut,
)
from app.modules.risk_management.service import (
    RISK_ARTEFACT_TYPE,
    RISK_MODULE_KEY,
    RISK_SUBCOMPONENT_KEY,
    RISK_TYPES,
    archive_risk,
    get_current_risk_version,
    list_project_risks,
    unarchive_risk,
)
from app.schemas.file import FileAssetOut
from app.schemas.type_vocabulary import EffectiveTypeOut, ProjectTypeCreate, ProjectTypeOut, ProjectTypeOverrideUpdate
from app.services.audit import log_event
from app.services.rbac import require_project_subcomponent_enabled

router = APIRouter(prefix=f"/api/v1/projects/{{project_id}}/modules/{RISK_MODULE_KEY}", tags=["risk-management-project"])

_require_view = require_project_subcomponent_enabled(RISK_MODULE_KEY, RISK_SUBCOMPONENT_KEY)


def _project(db: Session, project_id: UUID) -> Project:
    """Loads the project in the URL, 404ing if it does not exist."""
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found.")
    return project


def _get(db: Session, project_id: UUID, risk_id: UUID) -> Risk:
    """A risk of this project (404 for anything else)."""
    return sh.get_risk_in_project(db, project_id, risk_id)


# --- Risk type vocabulary (project half) -------------------------------------


@router.get("/risk-types", response_model=list[EffectiveTypeOut])
def list_project_risk_types(project_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db)):
    """The project's effective Risk type list (org types with overrides applied,
    plus project-local ones). Open to any project member so a type picker can be
    populated."""
    project = _project(db, project_id)
    return RISK_TYPES.resolve_effective(db, project_id, project.organization_id)


@router.post("/risk-types", response_model=ProjectTypeOut, status_code=status.HTTP_201_CREATED)
def create_project_local_risk_type(
    project_id: UUID, payload: ProjectTypeCreate, current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Creates a project-local Risk type. Needs the Risk Manager role; 400 on a duplicate name."""
    project = _project(db, project_id)
    sh.require_risk_manage(db, current_user, project)
    try:
        row = RISK_TYPES.create_project_local(db, project_id, payload.name, display_order=payload.display_order)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    log_event(db, entity_type="project_risk_type", entity_id=row.id, action="created", actor_id=current_user.id,
              project_id=project_id, detail={"name": payload.name})
    db.commit()
    db.refresh(row)
    return row


@router.put("/risk-types/{type_ref_id}", response_model=ProjectTypeOut)
def override_project_risk_type(
    project_id: UUID, type_ref_id: UUID, payload: ProjectTypeOverrideUpdate,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Partial override of a type here. `type_ref_id` is an `EffectiveTypeOut.id`:
    an org type gets its override row on first use."""
    project = _project(db, project_id)
    sh.require_risk_manage(db, current_user, project)
    try:
        row = RISK_TYPES.get_or_create_project_type(db, project_id, project.organization_id, type_ref_id)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    RISK_TYPES.set_override(db, row, name=payload.name, display_order=payload.display_order, is_enabled=payload.is_enabled)
    log_event(db, entity_type="project_risk_type", entity_id=row.id, action="updated", actor_id=current_user.id,
              project_id=project_id)
    db.commit()
    db.refresh(row)
    return row


@router.delete("/risk-types/{project_type_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project_risk_type(
    project_id: UUID, project_type_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Removes a project type row (an override reverts to the org default); 409
    while a risk still uses it."""
    project = _project(db, project_id)
    sh.require_risk_manage(db, current_user, project)
    row = db.get(ProjectRiskType, project_type_id)
    if row is None or row.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Risk type not found.")
    sh.apply_value_error_as_conflict(RISK_TYPES.delete_project_type, db, row)
    log_event(db, entity_type="project_risk_type", entity_id=project_type_id, action="deleted",
              actor_id=current_user.id, project_id=project_id)
    db.commit()


# --- Risk CRUD ---------------------------------------------------------------


@router.post("/risks", response_model=RiskOut, status_code=status.HTTP_201_CREATED)
def create_risk(
    project_id: UUID, payload: RiskCreate, current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Proposes a risk in `IDENTIFIED`. Any project member may do so (overview
    §11.7); assessing and managing it afterwards needs the Risk Manager role."""
    project = _project(db, project_id)
    return sh.create_risk_from_payload(db, payload, current_user, project)


@router.get("/risks", response_model=list[RiskOut])
def list_risks(
    project_id: UUID, include_archived: bool = False, current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """The project's risks with derived ratings; archived ones only with `include_archived`."""
    project = _project(db, project_id)
    ctx = load_rating_context(db, project)
    risks = list_project_risks(db, project_id, include_archived=include_archived)
    return [sh.risk_to_out(db, r, get_current_risk_version(db, r.id), ctx) for r in risks]


@router.get("/risks/{risk_id}", response_model=RiskOut)
def get_risk(project_id: UUID, risk_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db)):
    """One risk with its current version and derived ratings."""
    project = _project(db, project_id)
    return sh.current_risk_out(db, _get(db, project_id, risk_id), project)


@router.put("/risks/{risk_id}", response_model=RiskOut)
def update_risk(
    project_id: UUID, risk_id: UUID, payload: RiskUpdate,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Applies a partial update as a new version (fields absent from the body are
    kept). Needs the Risk Manager role."""
    project = _project(db, project_id)
    risk = _get(db, project_id, risk_id)
    sh.require_risk_manage(db, current_user, project)
    return sh.update_risk_from_payload(db, risk, payload, current_user, project)


@router.get("/risks/{risk_id}/versions", response_model=list[RiskVersionOut])
def list_risk_versions(project_id: UUID, risk_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db)):
    """A risk's full version history, oldest first."""
    _project(db, project_id)
    return _get(db, project_id, risk_id).versions


@router.post("/risks/{risk_id}/archive", response_model=RiskOut)
def archive(project_id: UUID, risk_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db)):
    """Soft-archives a risk. Needs the Risk Manager role."""
    project = _project(db, project_id)
    risk = _get(db, project_id, risk_id)
    sh.require_risk_manage(db, current_user, project)
    archive_risk(risk, current_user)
    log_event(db, entity_type=RISK_ARTEFACT_TYPE, entity_id=risk.id, action="archived", actor_id=current_user.id,
              project_id=project_id)
    db.commit()
    return sh.current_risk_out(db, risk, project)


@router.post("/risks/{risk_id}/unarchive", response_model=RiskOut)
def unarchive(project_id: UUID, risk_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db)):
    """Restores an archived risk. Needs the Risk Manager role."""
    project = _project(db, project_id)
    risk = _get(db, project_id, risk_id)
    sh.require_risk_manage(db, current_user, project)
    unarchive_risk(risk)
    log_event(db, entity_type=RISK_ARTEFACT_TYPE, entity_id=risk.id, action="unarchived", actor_id=current_user.id,
              project_id=project_id)
    db.commit()
    return sh.current_risk_out(db, risk, project)


# --- Comments ----------------------------------------------------------------


@router.post("/risks/{risk_id}/comments", response_model=RiskCommentOut, status_code=status.HTTP_201_CREATED)
def add_risk_comment(
    project_id: UUID, risk_id: UUID, payload: RiskCommentCreate,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Adds a discussion comment. Any project member may comment."""
    _project(db, project_id)
    return sh.add_comment(db, _get(db, project_id, risk_id), current_user, payload.body, project_id=project_id)


@router.get("/risks/{risk_id}/comments", response_model=list[RiskCommentOut])
def list_risk_comments(project_id: UUID, risk_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db)):
    """A risk's comments, oldest first, with attachments."""
    _project(db, project_id)
    return sh.list_comments(db, _get(db, project_id, risk_id))


@router.patch("/risks/{risk_id}/comments/{comment_id}", response_model=RiskCommentOut)
def edit_risk_comment(
    project_id: UUID, risk_id: UUID, comment_id: UUID, payload: RiskCommentUpdate,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Edits a comment. Author only."""
    _project(db, project_id)
    return sh.edit_comment(db, _get(db, project_id, risk_id), comment_id, current_user, payload.body, project_id=project_id)


@router.post("/risks/{risk_id}/comments/{comment_id}/files", response_model=FileAssetOut, status_code=status.HTTP_201_CREATED)
async def upload_risk_comment_attachment(
    project_id: UUID, risk_id: UUID, comment_id: UUID, file: UploadFile = File(...),
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Attaches a file to a comment. Comment author only."""
    project = _project(db, project_id)
    return await sh.attach_to_comment(
        db, _get(db, project_id, risk_id), comment_id, current_user, file,
        organization_id=project.organization_id, project_id=project_id,
    )


@router.delete("/risks/{risk_id}/comments/{comment_id}/files/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_risk_comment_attachment(
    project_id: UUID, risk_id: UUID, comment_id: UUID, file_id: UUID,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Removes (and deletes) a comment's attachment. Comment author only."""
    _project(db, project_id)
    sh.remove_comment_attachment(db, _get(db, project_id, risk_id), comment_id, file_id, current_user, project_id=project_id)


# --- Direct files (evidence) -------------------------------------------------


@router.post("/risks/{risk_id}/files", response_model=FileAssetOut, status_code=status.HTTP_201_CREATED)
async def upload_risk_file(
    project_id: UUID, risk_id: UUID, file: UploadFile = File(...),
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Uploads evidence directly to a risk. Needs the Risk Manager role."""
    project = _project(db, project_id)
    risk = _get(db, project_id, risk_id)
    sh.require_risk_manage(db, current_user, project)
    return await sh.attach_file(db, risk, current_user, file, organization_id=project.organization_id, project_id=project_id)


@router.get("/risks/{risk_id}/files", response_model=list[FileAssetOut])
def list_risk_files(project_id: UUID, risk_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db)):
    """Files attached directly to a risk."""
    _project(db, project_id)
    return sh.list_files(db, _get(db, project_id, risk_id))


@router.delete("/risks/{risk_id}/files/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
def unlink_risk_file(
    project_id: UUID, risk_id: UUID, file_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Removes (and deletes) a directly attached file. Needs the Risk Manager role."""
    project = _project(db, project_id)
    risk = _get(db, project_id, risk_id)
    sh.require_risk_manage(db, current_user, project)
    sh.unlink_file(db, risk, file_id, current_user, project_id=project_id)
