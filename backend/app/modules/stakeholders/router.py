"""
Module: modules.stakeholders.router

Org-scoped API for the Stakeholders & Personas module (Phase 1.1), mounted at
`/api/v1/orgs/{organization_id}/modules/stakeholders`: organisation-scoped
Persona CRUD/lifecycle/comments/files and the org Persona type vocabulary.

RBAC: reads are gated by `require_org_subcomponent_enabled("stakeholders",
"persona")` (any org member with the module and sub-component enabled);
mutations additionally require `_shared.require_persona_manage` (org persona
owner role or FGAC grant), and type CRUD `require_persona_type_admin`. An org
persona's files are org shared resources (`is_org_resource=True`), so the
file-owner hook is never consulted for them.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.organization import Organization
from app.models.user import User
from app.modules.stakeholders import _shared as sh
from app.modules.stakeholders.enums import PersonaScope, PersonaStatus
from app.modules.stakeholders.models import Persona, PersonaTypeDefinition
from app.modules.stakeholders.schemas import (
    PersonaCommentCreate,
    PersonaCommentOut,
    PersonaCommentUpdate,
    PersonaCreate,
    PersonaOut,
    PersonaTransitionRequest,
    PersonaTypeCreate,
    PersonaTypeOut,
    PersonaTypeUpdate,
    PersonaUpdate,
    PersonaVersionOut,
)
from app.modules.stakeholders.service import (
    PERSONA_ARTEFACT_TYPE,
    PERSONA_TYPES,
    archive_persona,
    get_current_persona_version,
    unarchive_persona,
)
from app.schemas.file import FileAssetOut
from app.schemas.project import MoveDirection
from app.services.audit import log_event
from app.services.ordering import move_ordered
from app.services.rbac import require_org_subcomponent_enabled

router = APIRouter(prefix="/api/v1/orgs/{organization_id}/modules/stakeholders", tags=["stakeholders-org"])

_SCOPE = PersonaScope.ORGANIZATION
_require_view = require_org_subcomponent_enabled("stakeholders", "persona")


def _get(db: Session, organization_id: UUID, persona_id: UUID) -> Persona:
    return sh.get_persona_in_scope(db, _SCOPE, organization_id=organization_id, persona_id=persona_id)


def _require_manage(db: Session, user: User, organization_id: UUID) -> None:
    sh.require_persona_manage(db, user, _SCOPE, organization_id=organization_id, project_id=None)


# --- Persona type vocabulary -------------------------------------------------


@router.get("/persona-types", response_model=list[PersonaTypeOut])
def list_persona_types(organization_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db)):
    """Lists the organisation's Persona types, including inactive ones (an
    admin needs to see and re-activate them)."""
    return db.scalars(
        select(PersonaTypeDefinition).where(PersonaTypeDefinition.organization_id == organization_id)
        .order_by(PersonaTypeDefinition.sort_order)
    ).all()


@router.post("/persona-types", response_model=PersonaTypeOut, status_code=status.HTTP_201_CREATED)
def create_persona_type(
    organization_id: UUID, payload: PersonaTypeCreate,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    sh.require_persona_type_admin(db, current_user, organization_id=organization_id)
    try:
        row = PERSONA_TYPES.create_org_type(db, organization_id, payload.name)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    log_event(db, entity_type="persona_type_definition", entity_id=row.id, action="created",
              actor_id=current_user.id, organization_id=organization_id, detail={"name": row.name})
    db.commit()
    db.refresh(row)
    return row


@router.post("/persona-types/{type_id}/move", response_model=PersonaTypeOut)
def move_persona_type(
    organization_id: UUID, type_id: UUID, payload: MoveDirection,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    sh.require_persona_type_admin(db, current_user, organization_id=organization_id)
    sh.get_org_type(db, organization_id, type_id)
    result = move_ordered(
        db, PersonaTypeDefinition, [PersonaTypeDefinition.organization_id == organization_id], type_id,
        payload.direction,
    )
    log_event(db, entity_type="persona_type_definition", entity_id=type_id, action="reordered",
              actor_id=current_user.id, organization_id=organization_id, detail={"direction": payload.direction})
    db.commit()
    return result


@router.patch("/persona-types/{type_id}", response_model=PersonaTypeOut)
def update_persona_type(
    organization_id: UUID, type_id: UUID, payload: PersonaTypeUpdate,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Renames and/or activates/deactivates a type. References are by id, so
    renaming never affects existing personas."""
    sh.require_persona_type_admin(db, current_user, organization_id=organization_id)
    row = sh.get_org_type(db, organization_id, type_id)
    if payload.name is not None:
        clash = db.scalar(select(PersonaTypeDefinition.id).where(
            PersonaTypeDefinition.organization_id == organization_id, PersonaTypeDefinition.name == payload.name,
            PersonaTypeDefinition.id != type_id,
        ))
        if clash is not None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "A Persona type with this name already exists.")
        row.name = payload.name
    if payload.is_active is not None:
        row.is_active = payload.is_active
    log_event(db, entity_type="persona_type_definition", entity_id=row.id, action="updated",
              actor_id=current_user.id, organization_id=organization_id)
    db.commit()
    db.refresh(row)
    return row


@router.delete("/persona-types/{type_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_persona_type(
    organization_id: UUID, type_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Deletes a type; 409 while any project or persona still references it."""
    sh.require_persona_type_admin(db, current_user, organization_id=organization_id)
    row = sh.get_org_type(db, organization_id, type_id)
    sh.apply_value_error_as_conflict(PERSONA_TYPES.delete_org_type, db, row)
    log_event(db, entity_type="persona_type_definition", entity_id=type_id, action="deleted",
              actor_id=current_user.id, organization_id=organization_id)
    db.commit()


# --- Persona CRUD ------------------------------------------------------------


@router.post("/personas", response_model=PersonaOut, status_code=status.HTTP_201_CREATED)
def create_org_persona(
    organization_id: UUID, payload: PersonaCreate,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Creates an org-scoped persona in `DRAFT`. Requires the org persona
    owner role (or FGAC grant)."""
    if db.get(Organization, organization_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organisation not found.")
    _require_manage(db, current_user, organization_id)
    return sh.create_persona_from_payload(db, _SCOPE, payload, current_user, organization_id=organization_id, project_id=None)


@router.get("/personas", response_model=list[PersonaOut])
def list_org_personas(
    organization_id: UUID, include_archived: bool = False,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    query = select(Persona).where(Persona.organization_id == organization_id, Persona.scope == _SCOPE)
    if not include_archived:
        query = query.where(Persona.is_archived.is_(False))
    return [
        sh.persona_to_out(db, p, get_current_persona_version(db, p.id))
        for p in db.scalars(query.order_by(Persona.created_at)).all()
    ]


@router.get("/personas/{persona_id}", response_model=PersonaOut)
def get_org_persona(
    organization_id: UUID, persona_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    persona = _get(db, organization_id, persona_id)
    return sh.persona_to_out(db, persona, get_current_persona_version(db, persona.id))


@router.put("/personas/{persona_id}", response_model=PersonaOut)
def update_org_persona(
    organization_id: UUID, persona_id: UUID, payload: PersonaUpdate,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Partial edit as a new version (any status — Personas have no content lock)."""
    persona = _get(db, organization_id, persona_id)
    _require_manage(db, current_user, organization_id)
    return sh.update_persona_from_payload(db, persona, payload, current_user, organization_id=organization_id, project_id=None)


@router.get("/personas/{persona_id}/versions", response_model=list[PersonaVersionOut])
def list_org_persona_versions(
    organization_id: UUID, persona_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    return _get(db, organization_id, persona_id).versions


@router.post("/personas/{persona_id}/archive", response_model=PersonaOut)
def archive_org_persona(
    organization_id: UUID, persona_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    persona = _get(db, organization_id, persona_id)
    _require_manage(db, current_user, organization_id)
    archive_persona(db, persona, current_user)
    log_event(db, entity_type=PERSONA_ARTEFACT_TYPE, entity_id=persona.id, action="archived",
              actor_id=current_user.id, organization_id=organization_id)
    db.commit()
    return sh.persona_to_out(db, persona, get_current_persona_version(db, persona.id))


@router.post("/personas/{persona_id}/unarchive", response_model=PersonaOut)
def unarchive_org_persona(
    organization_id: UUID, persona_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    persona = _get(db, organization_id, persona_id)
    _require_manage(db, current_user, organization_id)
    unarchive_persona(db, persona)
    log_event(db, entity_type=PERSONA_ARTEFACT_TYPE, entity_id=persona.id, action="unarchived",
              actor_id=current_user.id, organization_id=organization_id)
    db.commit()
    return sh.persona_to_out(db, persona, get_current_persona_version(db, persona.id))


@router.post("/personas/{persona_id}/activate", response_model=PersonaOut)
def activate_org_persona(
    organization_id: UUID, persona_id: UUID, payload: PersonaTransitionRequest | None = None,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """`DRAFT`/`RETIRED` -> `ACTIVE`."""
    persona = _get(db, organization_id, persona_id)
    _require_manage(db, current_user, organization_id)
    return sh.transition_persona_endpoint(
        db, persona, PersonaStatus.ACTIVE, current_user, action="activated",
        comment=payload.comment if payload else None, project_id=None,
    )


@router.post("/personas/{persona_id}/retire", response_model=PersonaOut)
def retire_org_persona(
    organization_id: UUID, persona_id: UUID, payload: PersonaTransitionRequest | None = None,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """`DRAFT`/`ACTIVE` -> `RETIRED`."""
    persona = _get(db, organization_id, persona_id)
    _require_manage(db, current_user, organization_id)
    return sh.transition_persona_endpoint(
        db, persona, PersonaStatus.RETIRED, current_user, action="retired",
        comment=payload.comment if payload else None, project_id=None,
    )


# --- Comments ----------------------------------------------------------------


@router.post("/personas/{persona_id}/comments", response_model=PersonaCommentOut, status_code=status.HTTP_201_CREATED)
def add_org_persona_comment(
    organization_id: UUID, persona_id: UUID, payload: PersonaCommentCreate,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    persona = _get(db, organization_id, persona_id)
    return sh.add_comment(db, persona, current_user, payload.body, organization_id=organization_id)


@router.get("/personas/{persona_id}/comments", response_model=list[PersonaCommentOut])
def list_org_persona_comments(
    organization_id: UUID, persona_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    return sh.list_comments(db, _get(db, organization_id, persona_id))


@router.patch("/personas/{persona_id}/comments/{comment_id}", response_model=PersonaCommentOut)
def edit_org_persona_comment(
    organization_id: UUID, persona_id: UUID, comment_id: UUID, payload: PersonaCommentUpdate,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    return sh.edit_comment(
        db, _get(db, organization_id, persona_id), comment_id, current_user, payload.body, organization_id=organization_id,
    )


@router.post("/personas/{persona_id}/comments/{comment_id}/files", response_model=FileAssetOut, status_code=status.HTTP_201_CREATED)
async def upload_org_persona_comment_attachment(
    organization_id: UUID, persona_id: UUID, comment_id: UUID, file: UploadFile = File(...),
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    persona = _get(db, organization_id, persona_id)
    return await sh.attach_to_comment(
        db, persona, comment_id, current_user, file, organization_id=organization_id,
    )


@router.delete("/personas/{persona_id}/comments/{comment_id}/files/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_org_persona_comment_attachment(
    organization_id: UUID, persona_id: UUID, comment_id: UUID, file_id: UUID,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    sh.remove_comment_attachment(
        db, _get(db, organization_id, persona_id), comment_id, file_id, current_user, organization_id=organization_id,
    )


# --- Direct files ------------------------------------------------------------


@router.post("/personas/{persona_id}/files", response_model=FileAssetOut, status_code=status.HTTP_201_CREATED)
async def upload_org_persona_file(
    organization_id: UUID, persona_id: UUID, file: UploadFile = File(...),
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    persona = _get(db, organization_id, persona_id)
    _require_manage(db, current_user, organization_id)
    return await sh.attach_file(db, persona, current_user, file, organization_id=organization_id)


@router.get("/personas/{persona_id}/files", response_model=list[FileAssetOut])
def list_org_persona_files(
    organization_id: UUID, persona_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    return sh.list_files(db, _get(db, organization_id, persona_id))


@router.delete("/personas/{persona_id}/files/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
def unlink_org_persona_file(
    organization_id: UUID, persona_id: UUID, file_id: UUID,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    persona = _get(db, organization_id, persona_id)
    _require_manage(db, current_user, organization_id)
    sh.unlink_file(db, persona, file_id, current_user, organization_id=organization_id)
