"""
Module: modules.stakeholders.project_router

Project-scoped API for the Stakeholders & Personas module (Phase 1.1), mounted
at `/api/v1/projects/{project_id}/modules/stakeholders`: project-scoped
Persona CRUD/lifecycle/comments/files, the project's Persona type vocabulary
(effective list plus rename/reorder/disable/add) and the per-project weight
override.

Reads (`GET /personas`, `GET /personas/{id}`) return the project's own
personas *and* the organisation's live org-scoped ones (Phase 0 resolution
2), each with the project's `effective_weight`. Every mutation targets a
project-scoped persona only; an org persona is edited through the org router.
The weight override is the one exception: a project may override the weight of
any persona it can see.

RBAC mirrors the org router: sub-component enablement to view,
`_shared.require_persona_manage` (project persona owner role or FGAC grant) to
change anything. A project persona's files resolve through
`service.resolve_persona_file_project_id`.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.project import Project
from app.models.user import User
from app.modules.stakeholders import _shared as sh
from app.modules.stakeholders.enums import PersonaScope, PersonaStatus
from app.modules.stakeholders.models import Persona, ProjectPersonaType
from app.modules.stakeholders.schemas import (
    EffectiveTypeOut,
    PersonaCommentCreate,
    PersonaCommentOut,
    PersonaCommentUpdate,
    PersonaCreate,
    PersonaOut,
    PersonaTransitionRequest,
    PersonaUpdate,
    PersonaVersionOut,
    PersonaWeightSet,
    ProjectTypeCreate,
    ProjectTypeOut,
    ProjectTypeOverrideUpdate,
)
from app.modules.stakeholders.service import (
    PERSONA_ARTEFACT_TYPE,
    PERSONA_TYPES,
    archive_persona,
    clear_project_persona_weight,
    get_current_persona_version,
    list_project_visible_personas,
    set_project_persona_weight,
    unarchive_persona,
)
from app.schemas.file import FileAssetOut
from app.services.audit import log_event
from app.services.rbac import require_project_subcomponent_enabled

router = APIRouter(prefix="/api/v1/projects/{project_id}/modules/stakeholders", tags=["stakeholders-project"])

_SCOPE = PersonaScope.PROJECT
_require_view = require_project_subcomponent_enabled("stakeholders", "persona")


def _project(db: Session, project_id: UUID) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found.")
    return project


def _get(db: Session, project_id: UUID, persona_id: UUID) -> Persona:
    """A project-scoped persona of this project (404 for anything else)."""
    return sh.get_persona_in_scope(db, _SCOPE, project_id=project_id, persona_id=persona_id)


def _get_visible(db: Session, project: Project, persona_id: UUID) -> Persona:
    """A persona this project can read: its own, or its organisation's."""
    persona = db.get(Persona, persona_id)
    visible = persona is not None and (
        (persona.scope == PersonaScope.PROJECT and persona.project_id == project.id)
        or (persona.scope == PersonaScope.ORGANIZATION and persona.organization_id == project.organization_id)
    )
    if not visible:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Persona not found.")
    return persona


def _require_manage(db: Session, user: User, project: Project) -> None:
    sh.require_persona_manage(db, user, _SCOPE, organization_id=project.organization_id, project_id=project.id)


def _out(db: Session, persona: Persona, project_id: UUID) -> PersonaOut:
    return sh.persona_to_out(db, persona, get_current_persona_version(db, persona.id), project_id=project_id)


# --- Persona type vocabulary (project half) ----------------------------------


@router.get("/persona-types", response_model=list[EffectiveTypeOut])
def list_project_persona_types(project_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db)):
    """The project's effective Persona type list (org types with overrides
    applied, plus project-local ones). Open to any project member so a type
    picker can be populated."""
    project = _project(db, project_id)
    return PERSONA_TYPES.resolve_effective(db, project_id, project.organization_id)


@router.post("/persona-types", response_model=ProjectTypeOut, status_code=status.HTTP_201_CREATED)
def create_project_local_persona_type(
    project_id: UUID, payload: ProjectTypeCreate, current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    project = _project(db, project_id)
    _require_manage(db, current_user, project)
    try:
        row = PERSONA_TYPES.create_project_local(db, project_id, payload.name, display_order=payload.display_order)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    log_event(db, entity_type="project_persona_type", entity_id=row.id, action="created", actor_id=current_user.id,
              project_id=project_id, detail={"name": payload.name})
    db.commit()
    db.refresh(row)
    return row


@router.put("/persona-types/{type_ref_id}", response_model=ProjectTypeOut)
def override_project_persona_type(
    project_id: UUID, type_ref_id: UUID, payload: ProjectTypeOverrideUpdate,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Partial override of a type here. `type_ref_id` is an
    `EffectiveTypeOut.id`: an org type gets its override row on first use."""
    project = _project(db, project_id)
    _require_manage(db, current_user, project)
    try:
        row = PERSONA_TYPES.get_or_create_project_type(db, project_id, project.organization_id, type_ref_id)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    PERSONA_TYPES.set_override(db, row, name=payload.name, display_order=payload.display_order, is_enabled=payload.is_enabled)
    log_event(db, entity_type="project_persona_type", entity_id=row.id, action="updated", actor_id=current_user.id,
              project_id=project_id)
    db.commit()
    db.refresh(row)
    return row


@router.delete("/persona-types/{project_type_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project_persona_type(
    project_id: UUID, project_type_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Removes a project type row (an override reverts to the org default);
    409 while a persona still uses it."""
    project = _project(db, project_id)
    _require_manage(db, current_user, project)
    row = db.get(ProjectPersonaType, project_type_id)
    if row is None or row.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Persona type not found.")
    sh.apply_value_error_as_conflict(PERSONA_TYPES.delete_project_type, db, row)
    log_event(db, entity_type="project_persona_type", entity_id=project_type_id, action="deleted",
              actor_id=current_user.id, project_id=project_id)
    db.commit()


# --- Persona CRUD ------------------------------------------------------------


@router.post("/personas", response_model=PersonaOut, status_code=status.HTTP_201_CREATED)
def create_project_persona(
    project_id: UUID, payload: PersonaCreate, current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Creates a project-scoped persona in `DRAFT`. Requires the persona
    owner role (or FGAC grant)."""
    project = _project(db, project_id)
    _require_manage(db, current_user, project)
    return sh.create_persona_from_payload(
        db, _SCOPE, payload, current_user, organization_id=project.organization_id, project_id=project_id,
    )


@router.get("/personas", response_model=list[PersonaOut])
def list_project_personas(
    project_id: UUID, include_archived: bool = False, include_org: bool = True,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """The project's personas, plus the organisation's unless `include_org=false`."""
    project = _project(db, project_id)
    personas = list_project_visible_personas(db, project, include_archived=include_archived)
    if not include_org:
        personas = [p for p in personas if p.scope == PersonaScope.PROJECT]
    return [_out(db, p, project_id) for p in personas]


@router.get("/personas/{persona_id}", response_model=PersonaOut)
def get_project_persona(
    project_id: UUID, persona_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    return _out(db, _get_visible(db, _project(db, project_id), persona_id), project_id)


@router.put("/personas/{persona_id}", response_model=PersonaOut)
def update_project_persona(
    project_id: UUID, persona_id: UUID, payload: PersonaUpdate,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    project = _project(db, project_id)
    persona = _get(db, project_id, persona_id)
    _require_manage(db, current_user, project)
    return sh.update_persona_from_payload(
        db, persona, payload, current_user, organization_id=project.organization_id, project_id=project_id,
    )


@router.get("/personas/{persona_id}/versions", response_model=list[PersonaVersionOut])
def list_project_persona_versions(
    project_id: UUID, persona_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    return _get_visible(db, _project(db, project_id), persona_id).versions


@router.post("/personas/{persona_id}/archive", response_model=PersonaOut)
def archive_project_persona(
    project_id: UUID, persona_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    project = _project(db, project_id)
    persona = _get(db, project_id, persona_id)
    _require_manage(db, current_user, project)
    archive_persona(db, persona, current_user)
    log_event(db, entity_type=PERSONA_ARTEFACT_TYPE, entity_id=persona.id, action="archived",
              actor_id=current_user.id, project_id=project_id)
    db.commit()
    return _out(db, persona, project_id)


@router.post("/personas/{persona_id}/unarchive", response_model=PersonaOut)
def unarchive_project_persona(
    project_id: UUID, persona_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    project = _project(db, project_id)
    persona = _get(db, project_id, persona_id)
    _require_manage(db, current_user, project)
    unarchive_persona(db, persona)
    log_event(db, entity_type=PERSONA_ARTEFACT_TYPE, entity_id=persona.id, action="unarchived",
              actor_id=current_user.id, project_id=project_id)
    db.commit()
    return _out(db, persona, project_id)


@router.post("/personas/{persona_id}/activate", response_model=PersonaOut)
def activate_project_persona(
    project_id: UUID, persona_id: UUID, payload: PersonaTransitionRequest | None = None,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """`DRAFT`/`RETIRED` -> `ACTIVE`."""
    project = _project(db, project_id)
    persona = _get(db, project_id, persona_id)
    _require_manage(db, current_user, project)
    return sh.transition_persona_endpoint(
        db, persona, PersonaStatus.ACTIVE, current_user, action="activated",
        comment=payload.comment if payload else None, project_id=project_id,
    )


@router.post("/personas/{persona_id}/retire", response_model=PersonaOut)
def retire_project_persona(
    project_id: UUID, persona_id: UUID, payload: PersonaTransitionRequest | None = None,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """`DRAFT`/`ACTIVE` -> `RETIRED`."""
    project = _project(db, project_id)
    persona = _get(db, project_id, persona_id)
    _require_manage(db, current_user, project)
    return sh.transition_persona_endpoint(
        db, persona, PersonaStatus.RETIRED, current_user, action="retired",
        comment=payload.comment if payload else None, project_id=project_id,
    )


# --- Weight override ---------------------------------------------------------


@router.put("/personas/{persona_id}/weight", response_model=PersonaOut)
def set_project_persona_weight_endpoint(
    project_id: UUID, persona_id: UUID, payload: PersonaWeightSet,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Sets this project's weight override for a persona it can see (its own
    or an org persona)."""
    project = _project(db, project_id)
    persona = _get_visible(db, project, persona_id)
    _require_manage(db, current_user, project)
    set_project_persona_weight(db, project_id, persona.id, payload.weight)
    log_event(db, entity_type=PERSONA_ARTEFACT_TYPE, entity_id=persona.id, action="weight_override_set",
              actor_id=current_user.id, project_id=project_id, detail={"weight": payload.weight})
    db.commit()
    return _out(db, persona, project_id)


@router.delete("/personas/{persona_id}/weight", response_model=PersonaOut)
def clear_project_persona_weight_endpoint(
    project_id: UUID, persona_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Removes this project's weight override, reverting to inherited/own weight."""
    project = _project(db, project_id)
    persona = _get_visible(db, project, persona_id)
    _require_manage(db, current_user, project)
    if clear_project_persona_weight(db, project_id, persona.id):
        log_event(db, entity_type=PERSONA_ARTEFACT_TYPE, entity_id=persona.id, action="weight_override_cleared",
                  actor_id=current_user.id, project_id=project_id)
    db.commit()
    return _out(db, persona, project_id)


# --- Comments ----------------------------------------------------------------


@router.post("/personas/{persona_id}/comments", response_model=PersonaCommentOut, status_code=status.HTTP_201_CREATED)
def add_project_persona_comment(
    project_id: UUID, persona_id: UUID, payload: PersonaCommentCreate,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    persona = _get_visible(db, _project(db, project_id), persona_id)
    return sh.add_comment(db, persona, current_user, payload.body, project_id=project_id)


@router.get("/personas/{persona_id}/comments", response_model=list[PersonaCommentOut])
def list_project_persona_comments(
    project_id: UUID, persona_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    return sh.list_comments(db, _get_visible(db, _project(db, project_id), persona_id))


@router.patch("/personas/{persona_id}/comments/{comment_id}", response_model=PersonaCommentOut)
def edit_project_persona_comment(
    project_id: UUID, persona_id: UUID, comment_id: UUID, payload: PersonaCommentUpdate,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    persona = _get_visible(db, _project(db, project_id), persona_id)
    return sh.edit_comment(db, persona, comment_id, current_user, payload.body, project_id=project_id)


@router.post("/personas/{persona_id}/comments/{comment_id}/files", response_model=FileAssetOut, status_code=status.HTTP_201_CREATED)
async def upload_project_persona_comment_attachment(
    project_id: UUID, persona_id: UUID, comment_id: UUID, file: UploadFile = File(...),
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    project = _project(db, project_id)
    persona = _get_visible(db, project, persona_id)
    return await sh.attach_to_comment(
        db, persona, comment_id, current_user, file, organization_id=project.organization_id, project_id=project_id,
    )


@router.delete("/personas/{persona_id}/comments/{comment_id}/files/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_project_persona_comment_attachment(
    project_id: UUID, persona_id: UUID, comment_id: UUID, file_id: UUID,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    persona = _get_visible(db, _project(db, project_id), persona_id)
    sh.remove_comment_attachment(db, persona, comment_id, file_id, current_user, project_id=project_id)


# --- Direct files ------------------------------------------------------------


@router.post("/personas/{persona_id}/files", response_model=FileAssetOut, status_code=status.HTTP_201_CREATED)
async def upload_project_persona_file(
    project_id: UUID, persona_id: UUID, file: UploadFile = File(...),
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    project = _project(db, project_id)
    persona = _get(db, project_id, persona_id)
    _require_manage(db, current_user, project)
    return await sh.attach_file(db, persona, current_user, file, organization_id=project.organization_id, project_id=project_id)


@router.get("/personas/{persona_id}/files", response_model=list[FileAssetOut])
def list_project_persona_files(
    project_id: UUID, persona_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    return sh.list_files(db, _get_visible(db, _project(db, project_id), persona_id))


@router.delete("/personas/{persona_id}/files/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
def unlink_project_persona_file(
    project_id: UUID, persona_id: UUID, file_id: UUID,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    project = _project(db, project_id)
    persona = _get(db, project_id, persona_id)
    _require_manage(db, current_user, project)
    sh.unlink_file(db, persona, file_id, current_user, project_id=project_id)
