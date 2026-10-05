"""
Module: modules.stakeholders.need_project_router

Project-scoped Stakeholder Need API (Phase 2), mounted at
`/api/v1/projects/{project_id}/modules/stakeholders` beside the Persona and
Stakeholder project routers: need CRUD/lifecycle/comments/files, the "has need"
links to Stakeholders and Personas, the "gives rise to" links to Requirements,
and the read-only needs list of a Stakeholder or Persona.

A Need is always project-scoped (no org router exists). RBAC: sub-component
enablement to view; `_need_shared.require_need_manage` to change anything
(including links). A need's files resolve through
`service.resolve_need_file_project_id`.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.project import Project
from app.models.user import User
from app.modules.stakeholders import _need_shared as nd
from app.modules.stakeholders.enums import NeedStatus
from app.modules.stakeholders.models import StakeholderNeed
from app.modules.stakeholders.schemas import (
    HeldNeedOut,
    NeedCommentCreate,
    NeedCommentOut,
    NeedCommentUpdate,
    NeedCreate,
    NeedHolderCreate,
    NeedHolderOut,
    NeedOut,
    NeedRequirementCreate,
    NeedRequirementOut,
    NeedTransitionRequest,
    NeedUpdate,
    NeedVersionOut,
)
from app.modules.stakeholders.service import (
    NEED_ARTEFACT_TYPE,
    PERSONA_ARTEFACT_TYPE,
    STAKEHOLDER_ARTEFACT_TYPE,
    archive_record,
    get_current_need_version,
    list_holder_needs,
    list_project_needs,
    unarchive_record,
)
from app.schemas.file import FileAssetOut
from app.services.audit import log_event
from app.services.rbac import require_project_subcomponent_enabled

router = APIRouter(prefix="/api/v1/projects/{project_id}/modules/stakeholders", tags=["stakeholder-needs-project"])

_require_view = require_project_subcomponent_enabled("stakeholders", "stakeholder_need")


def _project(db: Session, project_id: UUID) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found.")
    return project


def _get(db: Session, project_id: UUID, need_id: UUID) -> StakeholderNeed:
    return nd.get_need_in_project(db, project_id, need_id)


def _out(db: Session, need: StakeholderNeed) -> NeedOut:
    return nd.need_to_out(need, get_current_need_version(db, need.id))


# --- Need CRUD ---------------------------------------------------------------


@router.post("/needs", response_model=NeedOut, status_code=status.HTTP_201_CREATED)
def create_need(
    project_id: UUID, payload: NeedCreate, current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Creates a need in `DRAFT`. Requires the Stakeholder Need owner role (or FGAC grant)."""
    project = _project(db, project_id)
    nd.require_need_manage(db, current_user, project)
    return nd.create_need_from_payload(db, payload, current_user, project)


@router.get("/needs", response_model=list[NeedOut])
def list_needs(
    project_id: UUID, include_archived: bool = False,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    _project(db, project_id)
    return [_out(db, n) for n in list_project_needs(db, project_id, include_archived=include_archived)]


@router.get("/needs/{need_id}", response_model=NeedOut)
def get_need(project_id: UUID, need_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db)):
    _project(db, project_id)
    return _out(db, _get(db, project_id, need_id))


@router.put("/needs/{need_id}", response_model=NeedOut)
def update_need(
    project_id: UUID, need_id: UUID, payload: NeedUpdate,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    project = _project(db, project_id)
    need = _get(db, project_id, need_id)
    nd.require_need_manage(db, current_user, project)
    return nd.update_need_from_payload(db, need, payload, current_user, project)


@router.get("/needs/{need_id}/versions", response_model=list[NeedVersionOut])
def list_need_versions(
    project_id: UUID, need_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    _project(db, project_id)
    return _get(db, project_id, need_id).versions


@router.post("/needs/{need_id}/archive", response_model=NeedOut)
def archive_need(project_id: UUID, need_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db)):
    project = _project(db, project_id)
    need = _get(db, project_id, need_id)
    nd.require_need_manage(db, current_user, project)
    archive_record(db, need, current_user)
    log_event(db, entity_type=NEED_ARTEFACT_TYPE, entity_id=need.id, action="archived", actor_id=current_user.id,
              project_id=project_id)
    db.commit()
    return _out(db, need)


@router.post("/needs/{need_id}/unarchive", response_model=NeedOut)
def unarchive_need(project_id: UUID, need_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db)):
    project = _project(db, project_id)
    need = _get(db, project_id, need_id)
    nd.require_need_manage(db, current_user, project)
    unarchive_record(db, need)
    log_event(db, entity_type=NEED_ARTEFACT_TYPE, entity_id=need.id, action="unarchived", actor_id=current_user.id,
              project_id=project_id)
    db.commit()
    return _out(db, need)


@router.post("/needs/{need_id}/activate", response_model=NeedOut)
def activate_need(
    project_id: UUID, need_id: UUID, payload: NeedTransitionRequest | None = None,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """`DRAFT`/`RETIRED` -> `ACTIVE`."""
    project = _project(db, project_id)
    need = _get(db, project_id, need_id)
    nd.require_need_manage(db, current_user, project)
    return nd.transition_need_endpoint(
        db, need, NeedStatus.ACTIVE, current_user, action="activated", comment=payload.comment if payload else None
    )


@router.post("/needs/{need_id}/retire", response_model=NeedOut)
def retire_need(
    project_id: UUID, need_id: UUID, payload: NeedTransitionRequest | None = None,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """`DRAFT`/`ACTIVE` -> `RETIRED`."""
    project = _project(db, project_id)
    need = _get(db, project_id, need_id)
    nd.require_need_manage(db, current_user, project)
    return nd.transition_need_endpoint(
        db, need, NeedStatus.RETIRED, current_user, action="retired", comment=payload.comment if payload else None
    )


# --- "Has need": Stakeholders and Personas -----------------------------------


@router.get("/needs/{need_id}/holders", response_model=list[NeedHolderOut])
def list_need_holders(project_id: UUID, need_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db)):
    """The Stakeholders and Personas that have this need and that this project can see."""
    project = _project(db, project_id)
    return nd.list_holders(db, _get(db, project_id, need_id), project)


@router.post("/needs/{need_id}/holders", response_model=NeedHolderOut, status_code=status.HTTP_201_CREATED)
def add_need_holder(
    project_id: UUID, need_id: UUID, payload: NeedHolderCreate,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Records that a Stakeholder or Persona this project can see has the need (409 on a duplicate)."""
    project = _project(db, project_id)
    need = _get(db, project_id, need_id)
    nd.require_need_manage(db, current_user, project)
    return nd.add_holder(db, need, payload.kind, payload.id, current_user, project)


@router.delete("/needs/{need_id}/holders/{kind}/{holder_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_need_holder(
    project_id: UUID, need_id: UUID, kind: str, holder_id: UUID,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    project = _project(db, project_id)
    need = _get(db, project_id, need_id)
    nd.require_need_manage(db, current_user, project)
    if kind not in (STAKEHOLDER_ARTEFACT_TYPE, PERSONA_ARTEFACT_TYPE):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That record does not have this need.")
    nd.remove_holder(db, need, kind, holder_id, current_user, project)


@router.get("/stakeholders/{stakeholder_id}/needs", response_model=list[HeldNeedOut])
def list_stakeholder_needs(
    project_id: UUID, stakeholder_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """The needs of this project that a visible Stakeholder has."""
    project = _project(db, project_id)
    record = nd.get_visible_holder(db, project, STAKEHOLDER_ARTEFACT_TYPE, stakeholder_id)
    return [
        nd.held_need_to_out(db, link, need)
        for link, need in list_holder_needs(db, STAKEHOLDER_ARTEFACT_TYPE, record.id, project.organization_id, project_id)
    ]


@router.get("/personas/{persona_id}/needs", response_model=list[HeldNeedOut])
def list_persona_needs(
    project_id: UUID, persona_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """The needs of this project that a visible Persona has."""
    project = _project(db, project_id)
    record = nd.get_visible_holder(db, project, PERSONA_ARTEFACT_TYPE, persona_id)
    return [
        nd.held_need_to_out(db, link, need)
        for link, need in list_holder_needs(db, PERSONA_ARTEFACT_TYPE, record.id, project.organization_id, project_id)
    ]


# --- "Gives rise to": Requirements -------------------------------------------


@router.get("/needs/{need_id}/requirements", response_model=list[NeedRequirementOut])
def list_need_requirements(project_id: UUID, need_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db)):
    project = _project(db, project_id)
    return nd.list_requirements(db, _get(db, project_id, need_id), project)


@router.post("/needs/{need_id}/requirements", response_model=NeedRequirementOut, status_code=status.HTTP_201_CREATED)
def add_need_requirement(
    project_id: UUID, need_id: UUID, payload: NeedRequirementCreate,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Records that the need gave rise to a Requirement of this project (409 on a duplicate)."""
    project = _project(db, project_id)
    need = _get(db, project_id, need_id)
    nd.require_need_manage(db, current_user, project)
    return nd.add_requirement(db, need, payload.requirement_id, current_user, project)


@router.delete("/needs/{need_id}/requirements/{requirement_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_need_requirement(
    project_id: UUID, need_id: UUID, requirement_id: UUID,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    project = _project(db, project_id)
    need = _get(db, project_id, need_id)
    nd.require_need_manage(db, current_user, project)
    nd.remove_requirement(db, need, requirement_id, current_user, project)


# --- Comments ----------------------------------------------------------------


@router.post("/needs/{need_id}/comments", response_model=NeedCommentOut, status_code=status.HTTP_201_CREATED)
def add_need_comment(
    project_id: UUID, need_id: UUID, payload: NeedCommentCreate,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    _project(db, project_id)
    return nd.add_comment(db, _get(db, project_id, need_id), current_user, payload.body, project_id=project_id)


@router.get("/needs/{need_id}/comments", response_model=list[NeedCommentOut])
def list_need_comments(project_id: UUID, need_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db)):
    _project(db, project_id)
    return nd.list_comments(db, _get(db, project_id, need_id))


@router.patch("/needs/{need_id}/comments/{comment_id}", response_model=NeedCommentOut)
def edit_need_comment(
    project_id: UUID, need_id: UUID, comment_id: UUID, payload: NeedCommentUpdate,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    _project(db, project_id)
    return nd.edit_comment(db, _get(db, project_id, need_id), comment_id, current_user, payload.body, project_id=project_id)


@router.post("/needs/{need_id}/comments/{comment_id}/files", response_model=FileAssetOut, status_code=status.HTTP_201_CREATED)
async def upload_need_comment_attachment(
    project_id: UUID, need_id: UUID, comment_id: UUID, file: UploadFile = File(...),
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    project = _project(db, project_id)
    return await nd.attach_to_comment(
        db, _get(db, project_id, need_id), comment_id, current_user, file,
        organization_id=project.organization_id, project_id=project_id,
    )


@router.delete("/needs/{need_id}/comments/{comment_id}/files/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_need_comment_attachment(
    project_id: UUID, need_id: UUID, comment_id: UUID, file_id: UUID,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    _project(db, project_id)
    nd.remove_comment_attachment(
        db, _get(db, project_id, need_id), comment_id, file_id, current_user, project_id=project_id
    )


# --- Direct files ------------------------------------------------------------


@router.post("/needs/{need_id}/files", response_model=FileAssetOut, status_code=status.HTTP_201_CREATED)
async def upload_need_file(
    project_id: UUID, need_id: UUID, file: UploadFile = File(...),
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    project = _project(db, project_id)
    need = _get(db, project_id, need_id)
    nd.require_need_manage(db, current_user, project)
    return await nd.attach_file(
        db, need, current_user, file, organization_id=project.organization_id, project_id=project_id
    )


@router.get("/needs/{need_id}/files", response_model=list[FileAssetOut])
def list_need_files(project_id: UUID, need_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db)):
    _project(db, project_id)
    return nd.list_files(db, _get(db, project_id, need_id))


@router.delete("/needs/{need_id}/files/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
def unlink_need_file(
    project_id: UUID, need_id: UUID, file_id: UUID,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    project = _project(db, project_id)
    need = _get(db, project_id, need_id)
    nd.require_need_manage(db, current_user, project)
    nd.unlink_file(db, need, file_id, current_user, project_id=project_id)
