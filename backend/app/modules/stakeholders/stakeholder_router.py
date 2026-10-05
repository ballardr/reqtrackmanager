"""
Module: modules.stakeholders.stakeholder_router

Org-scoped Stakeholder API (Phase 1.2), mounted at
`/api/v1/orgs/{organization_id}/modules/stakeholders`, alongside `router.py`'s
Persona routes: organisation-scoped Stakeholder CRUD/lifecycle/comments/files,
the org Stakeholder type vocabulary, "create from org user", the Influence ×
Interest cadence hint, hard delete (erasure) and the "represents Persona" links.

RBAC mirrors the Persona router: reads are gated by
`require_org_subcomponent_enabled("stakeholders", "stakeholder")`; mutations
additionally need `_stakeholder_shared.require_stakeholder_manage`, and type
CRUD `require_stakeholder_type_admin`. An org stakeholder's files are org
shared resources, so the file-owner hook is never consulted for them. An org
stakeholder only represents org-scoped personas, and the persona-side reverse
list shows only org-scoped stakeholders, so org-level views never expose a
project's own records.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.organization import Organization
from app.models.user import User
from app.modules.stakeholders import _shared as psh
from app.modules.stakeholders import _stakeholder_shared as sh
from app.modules.stakeholders.enums import PersonaScope, StakeholderScope, StakeholderStatus
from app.modules.stakeholders.models import Stakeholder, StakeholderTypeDefinition
from app.modules.stakeholders.schemas import (
    CadenceHintOut,
    RepresentedPersonaOut,
    RepresentsCreate,
    StakeholderCommentCreate,
    StakeholderCommentOut,
    StakeholderCommentUpdate,
    StakeholderCreate,
    StakeholderFromUserCreate,
    StakeholderOut,
    StakeholderTransitionRequest,
    StakeholderTypeCreate,
    StakeholderTypeOut,
    StakeholderTypeUpdate,
    StakeholderUpdate,
    StakeholderVersionOut,
)
from app.modules.stakeholders.service import (
    STAKEHOLDER_ARTEFACT_TYPE,
    STAKEHOLDER_TYPES,
    archive_record,
    delete_represents_link,
    get_current_stakeholder_version,
    grid_quadrant,
    list_represented_personas,
    list_representing_stakeholders,
    suggest_cadence,
    unarchive_record,
)
from app.schemas.file import FileAssetOut
from app.schemas.project import MoveDirection
from app.services.audit import log_event
from app.services.ordering import move_ordered
from app.services.rbac import require_org_subcomponent_enabled

router = APIRouter(prefix="/api/v1/orgs/{organization_id}/modules/stakeholders", tags=["stakeholders-org"])

_SCOPE = StakeholderScope.ORGANIZATION
_require_view = require_org_subcomponent_enabled("stakeholders", "stakeholder")


def _get(db: Session, organization_id: UUID, stakeholder_id: UUID) -> Stakeholder:
    return sh.get_stakeholder_in_scope(db, _SCOPE, organization_id=organization_id, stakeholder_id=stakeholder_id)


def _require_manage(db: Session, user: User, organization_id: UUID) -> None:
    sh.require_stakeholder_manage(db, user, _SCOPE, organization_id=organization_id, project_id=None)


def _out(db: Session, stakeholder: Stakeholder) -> StakeholderOut:
    return sh.stakeholder_to_out(db, stakeholder, get_current_stakeholder_version(db, stakeholder.id))


def _require_org(db: Session, organization_id: UUID) -> None:
    if db.get(Organization, organization_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organisation not found.")


# --- Stakeholder type vocabulary ---------------------------------------------


def _get_type(db: Session, organization_id: UUID, type_id: UUID) -> StakeholderTypeDefinition:
    row = db.get(StakeholderTypeDefinition, type_id)
    if row is None or row.organization_id != organization_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Stakeholder type not found.")
    return row


@router.get("/stakeholder-types", response_model=list[StakeholderTypeOut])
def list_stakeholder_types(organization_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db)):
    """Lists the organisation's Stakeholder types, including inactive ones (an
    admin needs to see and re-activate them)."""
    return db.scalars(
        select(StakeholderTypeDefinition).where(StakeholderTypeDefinition.organization_id == organization_id)
        .order_by(StakeholderTypeDefinition.sort_order)
    ).all()


@router.post("/stakeholder-types", response_model=StakeholderTypeOut, status_code=status.HTTP_201_CREATED)
def create_stakeholder_type(
    organization_id: UUID, payload: StakeholderTypeCreate,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    sh.require_stakeholder_type_admin(db, current_user, organization_id=organization_id)
    try:
        row = STAKEHOLDER_TYPES.create_org_type(db, organization_id, payload.name)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    log_event(db, entity_type="stakeholder_type_definition", entity_id=row.id, action="created",
              actor_id=current_user.id, organization_id=organization_id, detail={"name": row.name})
    db.commit()
    db.refresh(row)
    return row


@router.post("/stakeholder-types/{type_id}/move", response_model=StakeholderTypeOut)
def move_stakeholder_type(
    organization_id: UUID, type_id: UUID, payload: MoveDirection,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    sh.require_stakeholder_type_admin(db, current_user, organization_id=organization_id)
    _get_type(db, organization_id, type_id)
    result = move_ordered(
        db, StakeholderTypeDefinition, [StakeholderTypeDefinition.organization_id == organization_id], type_id,
        payload.direction,
    )
    log_event(db, entity_type="stakeholder_type_definition", entity_id=type_id, action="reordered",
              actor_id=current_user.id, organization_id=organization_id, detail={"direction": payload.direction})
    db.commit()
    return result


@router.patch("/stakeholder-types/{type_id}", response_model=StakeholderTypeOut)
def update_stakeholder_type(
    organization_id: UUID, type_id: UUID, payload: StakeholderTypeUpdate,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Renames and/or activates/deactivates a type. References are by id, so
    renaming never affects existing stakeholders."""
    sh.require_stakeholder_type_admin(db, current_user, organization_id=organization_id)
    row = _get_type(db, organization_id, type_id)
    if payload.name is not None:
        clash = db.scalar(select(StakeholderTypeDefinition.id).where(
            StakeholderTypeDefinition.organization_id == organization_id,
            StakeholderTypeDefinition.name == payload.name, StakeholderTypeDefinition.id != type_id,
        ))
        if clash is not None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "A Stakeholder type with this name already exists.")
        row.name = payload.name
    if payload.is_active is not None:
        row.is_active = payload.is_active
    log_event(db, entity_type="stakeholder_type_definition", entity_id=row.id, action="updated",
              actor_id=current_user.id, organization_id=organization_id)
    db.commit()
    db.refresh(row)
    return row


@router.delete("/stakeholder-types/{type_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_stakeholder_type(
    organization_id: UUID, type_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Deletes a type; 409 while any project or stakeholder still references it."""
    sh.require_stakeholder_type_admin(db, current_user, organization_id=organization_id)
    row = _get_type(db, organization_id, type_id)
    psh.apply_value_error_as_conflict(STAKEHOLDER_TYPES.delete_org_type, db, row)
    log_event(db, entity_type="stakeholder_type_definition", entity_id=type_id, action="deleted",
              actor_id=current_user.id, organization_id=organization_id)
    db.commit()


# --- Cadence hint ------------------------------------------------------------


@router.get("/stakeholders/cadence-hint", response_model=CadenceHintOut)
def get_cadence_hint(
    organization_id: UUID, influence_level_id: UUID | None = None, interest_level_id: UUID | None = None,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """The power/interest quadrant and suggested cadence for a pair of levels
    (resolution 21); a hint only. Declared before `/stakeholders/{id}` so the
    literal path wins."""
    try:
        quadrant = grid_quadrant(
            db, organization_id, influence_level_id=influence_level_id, interest_level_id=interest_level_id
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return CadenceHintOut(quadrant=quadrant, suggested_cadence=suggest_cadence(quadrant))


# --- Stakeholder CRUD --------------------------------------------------------


@router.post("/stakeholders", response_model=StakeholderOut, status_code=status.HTTP_201_CREATED)
def create_org_stakeholder(
    organization_id: UUID, payload: StakeholderCreate,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Creates an org-scoped stakeholder in `DRAFT`. Requires the org
    stakeholder owner role (or FGAC grant)."""
    _require_org(db, organization_id)
    _require_manage(db, current_user, organization_id)
    return sh.create_stakeholder_from_payload(
        db, _SCOPE, payload, current_user, organization_id=organization_id, project_id=None
    )


@router.post("/stakeholders/from-user", response_model=StakeholderOut, status_code=status.HTTP_201_CREATED)
def create_org_stakeholder_from_user(
    organization_id: UUID, payload: StakeholderFromUserCreate,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Creates an org-scoped stakeholder from an org user (name and contact
    prefilled); 409 if one already represents them."""
    _require_org(db, organization_id)
    _require_manage(db, current_user, organization_id)
    return sh.create_stakeholder_from_user(
        db, _SCOPE, payload, current_user, organization_id=organization_id, project_id=None
    )


@router.get("/stakeholders", response_model=list[StakeholderOut])
def list_org_stakeholders(
    organization_id: UUID, include_archived: bool = False,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    query = select(Stakeholder).where(Stakeholder.organization_id == organization_id, Stakeholder.scope == _SCOPE)
    if not include_archived:
        query = query.where(Stakeholder.is_archived.is_(False))
    return [_out(db, s) for s in db.scalars(query.order_by(Stakeholder.created_at)).all()]


@router.get("/stakeholders/{stakeholder_id}", response_model=StakeholderOut)
def get_org_stakeholder(
    organization_id: UUID, stakeholder_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    return _out(db, _get(db, organization_id, stakeholder_id))


@router.put("/stakeholders/{stakeholder_id}", response_model=StakeholderOut)
def update_org_stakeholder(
    organization_id: UUID, stakeholder_id: UUID, payload: StakeholderUpdate,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Partial edit as a new version (any status — no content lock)."""
    stakeholder = _get(db, organization_id, stakeholder_id)
    _require_manage(db, current_user, organization_id)
    return sh.update_stakeholder_from_payload(
        db, stakeholder, payload, current_user, organization_id=organization_id, project_id=None
    )


@router.get("/stakeholders/{stakeholder_id}/versions", response_model=list[StakeholderVersionOut])
def list_org_stakeholder_versions(
    organization_id: UUID, stakeholder_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    return _get(db, organization_id, stakeholder_id).versions


@router.delete("/stakeholders/{stakeholder_id}", status_code=status.HTTP_204_NO_CONTENT)
def erase_org_stakeholder(
    organization_id: UUID, stakeholder_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Permanently deletes a stakeholder and every row/file/link holding data
    about them (Phase 0 resolution 15). Irreversible; the audit event keeps
    only the id."""
    stakeholder = _get(db, organization_id, stakeholder_id)
    _require_manage(db, current_user, organization_id)
    sh.erase_stakeholder_endpoint(db, stakeholder, current_user)


@router.post("/stakeholders/{stakeholder_id}/archive", response_model=StakeholderOut)
def archive_org_stakeholder(
    organization_id: UUID, stakeholder_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    stakeholder = _get(db, organization_id, stakeholder_id)
    _require_manage(db, current_user, organization_id)
    archive_record(db, stakeholder, current_user)
    log_event(db, entity_type=STAKEHOLDER_ARTEFACT_TYPE, entity_id=stakeholder.id, action="archived",
              actor_id=current_user.id, organization_id=organization_id)
    db.commit()
    return _out(db, stakeholder)


@router.post("/stakeholders/{stakeholder_id}/unarchive", response_model=StakeholderOut)
def unarchive_org_stakeholder(
    organization_id: UUID, stakeholder_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    stakeholder = _get(db, organization_id, stakeholder_id)
    _require_manage(db, current_user, organization_id)
    unarchive_record(db, stakeholder)
    log_event(db, entity_type=STAKEHOLDER_ARTEFACT_TYPE, entity_id=stakeholder.id, action="unarchived",
              actor_id=current_user.id, organization_id=organization_id)
    db.commit()
    return _out(db, stakeholder)


@router.post("/stakeholders/{stakeholder_id}/activate", response_model=StakeholderOut)
def activate_org_stakeholder(
    organization_id: UUID, stakeholder_id: UUID, payload: StakeholderTransitionRequest | None = None,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """`DRAFT`/`RETIRED` -> `ACTIVE`."""
    stakeholder = _get(db, organization_id, stakeholder_id)
    _require_manage(db, current_user, organization_id)
    return sh.transition_stakeholder_endpoint(
        db, stakeholder, StakeholderStatus.ACTIVE, current_user, action="activated",
        comment=payload.comment if payload else None,
    )


@router.post("/stakeholders/{stakeholder_id}/retire", response_model=StakeholderOut)
def retire_org_stakeholder(
    organization_id: UUID, stakeholder_id: UUID, payload: StakeholderTransitionRequest | None = None,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """`DRAFT`/`ACTIVE` -> `RETIRED`."""
    stakeholder = _get(db, organization_id, stakeholder_id)
    _require_manage(db, current_user, organization_id)
    return sh.transition_stakeholder_endpoint(
        db, stakeholder, StakeholderStatus.RETIRED, current_user, action="retired",
        comment=payload.comment if payload else None,
    )


# --- Represents Persona ------------------------------------------------------


@router.get("/stakeholders/{stakeholder_id}/personas", response_model=list[RepresentedPersonaOut])
def list_org_stakeholder_personas(
    organization_id: UUID, stakeholder_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """The Personas this stakeholder represents."""
    stakeholder = _get(db, organization_id, stakeholder_id)
    return [sh.represents_to_out(db, link, p) for link, p in list_represented_personas(db, stakeholder, organization_id)]


@router.post("/stakeholders/{stakeholder_id}/personas", response_model=RepresentedPersonaOut, status_code=status.HTTP_201_CREATED)
def add_org_stakeholder_persona(
    organization_id: UUID, stakeholder_id: UUID, payload: RepresentsCreate,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Records that this stakeholder represents an org-scoped Persona (409 on
    a duplicate)."""
    stakeholder = _get(db, organization_id, stakeholder_id)
    persona = psh.get_persona_in_scope(
        db, PersonaScope.ORGANIZATION, organization_id=organization_id, persona_id=payload.persona_id
    )
    _require_manage(db, current_user, organization_id)
    return sh.add_represents(db, stakeholder, persona, current_user, organization_id=organization_id)


@router.delete("/stakeholders/{stakeholder_id}/personas/{persona_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_org_stakeholder_persona(
    organization_id: UUID, stakeholder_id: UUID, persona_id: UUID,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    stakeholder = _get(db, organization_id, stakeholder_id)
    _require_manage(db, current_user, organization_id)
    for link, persona in list_represented_personas(db, stakeholder, organization_id):
        if persona.id == persona_id:
            delete_represents_link(db, link)
            log_event(db, entity_type=STAKEHOLDER_ARTEFACT_TYPE, entity_id=stakeholder.id, action="represents_removed",
                      actor_id=current_user.id, organization_id=organization_id, detail={"persona_id": str(persona_id)})
            db.commit()
            return
    raise HTTPException(status.HTTP_404_NOT_FOUND, "This Stakeholder does not represent that Persona.")


@router.get("/personas/{persona_id}/stakeholders", response_model=list[RepresentedPersonaOut])
def list_org_persona_stakeholders(
    organization_id: UUID, persona_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """The org-scoped Stakeholders that represent this Persona (project-scoped
    ones are only listed on the project route)."""
    persona = psh.get_persona_in_scope(db, PersonaScope.ORGANIZATION, organization_id=organization_id, persona_id=persona_id)
    return [
        sh.stakeholder_link_to_out(db, link, s)
        for link, s in list_representing_stakeholders(db, persona, organization_id)
        if s.scope == StakeholderScope.ORGANIZATION
    ]


# --- Comments ----------------------------------------------------------------


@router.post("/stakeholders/{stakeholder_id}/comments", response_model=StakeholderCommentOut, status_code=status.HTTP_201_CREATED)
def add_org_stakeholder_comment(
    organization_id: UUID, stakeholder_id: UUID, payload: StakeholderCommentCreate,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    stakeholder = _get(db, organization_id, stakeholder_id)
    return sh.add_comment(db, stakeholder, current_user, payload.body, organization_id=organization_id)


@router.get("/stakeholders/{stakeholder_id}/comments", response_model=list[StakeholderCommentOut])
def list_org_stakeholder_comments(
    organization_id: UUID, stakeholder_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    return sh.list_comments(db, _get(db, organization_id, stakeholder_id))


@router.patch("/stakeholders/{stakeholder_id}/comments/{comment_id}", response_model=StakeholderCommentOut)
def edit_org_stakeholder_comment(
    organization_id: UUID, stakeholder_id: UUID, comment_id: UUID, payload: StakeholderCommentUpdate,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    stakeholder = _get(db, organization_id, stakeholder_id)
    return sh.edit_comment(db, stakeholder, comment_id, current_user, payload.body, organization_id=organization_id)


@router.post("/stakeholders/{stakeholder_id}/comments/{comment_id}/files", response_model=FileAssetOut, status_code=status.HTTP_201_CREATED)
async def upload_org_stakeholder_comment_attachment(
    organization_id: UUID, stakeholder_id: UUID, comment_id: UUID, file: UploadFile = File(...),
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    stakeholder = _get(db, organization_id, stakeholder_id)
    return await sh.attach_to_comment(
        db, stakeholder, comment_id, current_user, file, organization_id=organization_id,
    )


@router.delete("/stakeholders/{stakeholder_id}/comments/{comment_id}/files/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_org_stakeholder_comment_attachment(
    organization_id: UUID, stakeholder_id: UUID, comment_id: UUID, file_id: UUID,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    stakeholder = _get(db, organization_id, stakeholder_id)
    sh.remove_comment_attachment(
        db, stakeholder, comment_id, file_id, current_user, organization_id=organization_id
    )


# --- Direct files ------------------------------------------------------------


@router.post("/stakeholders/{stakeholder_id}/files", response_model=FileAssetOut, status_code=status.HTTP_201_CREATED)
async def upload_org_stakeholder_file(
    organization_id: UUID, stakeholder_id: UUID, file: UploadFile = File(...),
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    stakeholder = _get(db, organization_id, stakeholder_id)
    _require_manage(db, current_user, organization_id)
    return await sh.attach_file(db, stakeholder, current_user, file, organization_id=organization_id)


@router.get("/stakeholders/{stakeholder_id}/files", response_model=list[FileAssetOut])
def list_org_stakeholder_files(
    organization_id: UUID, stakeholder_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    return sh.list_files(db, _get(db, organization_id, stakeholder_id))


@router.delete("/stakeholders/{stakeholder_id}/files/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
def unlink_org_stakeholder_file(
    organization_id: UUID, stakeholder_id: UUID, file_id: UUID,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    stakeholder = _get(db, organization_id, stakeholder_id)
    _require_manage(db, current_user, organization_id)
    sh.unlink_file(db, stakeholder, file_id, current_user, organization_id=organization_id)
