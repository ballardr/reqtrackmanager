"""
Module: modules.stakeholders.stakeholder_project_router

Project-scoped Stakeholder API (Phase 1.2), mounted at
`/api/v1/projects/{project_id}/modules/stakeholders` alongside
`project_router.py`'s Persona routes: project-scoped Stakeholder
CRUD/lifecycle/comments/files/erasure, the project's Stakeholder type
vocabulary (effective list plus rename/reorder/disable/add), "create from org
user", the cadence hint, the "represents Persona" links and the project's
per-stakeholder visibility override (Phase 3b).

Reads return the project's own stakeholders *and* the organisation's live
org-scoped ones (Phase 0 resolution 2), minus org ones the project (or an
ancestor) has hidden. Every mutation targets a project-scoped stakeholder
only; an org stakeholder is edited through the org router — the one exception
is hiding/showing it, which writes only the project's own override row. A project stakeholder may represent an org persona or one of its own
project's personas; the persona-side reverse list is filtered to stakeholders
this project can see, so one project never learns of another's records.

RBAC mirrors the org router: sub-component enablement to view,
`_stakeholder_shared.require_stakeholder_manage` (project stakeholder owner
role or FGAC grant) to change anything. A project stakeholder's files resolve
through `service.resolve_stakeholder_file_project_id`.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.project import Project
from app.models.user import User
from app.modules.stakeholders import _shared as psh
from app.modules.stakeholders import _stakeholder_shared as sh
from app.modules.stakeholders._shared import get_visible_persona, get_visible_stakeholder
from app.modules.stakeholders.enums import PersonaScope, StakeholderScope, StakeholderStatus
from app.modules.stakeholders.models import ProjectStakeholderType, Stakeholder
from app.modules.stakeholders.schemas import (
    CadenceHintOut,
    EffectiveTypeOut,
    ProjectTypeCreate,
    ProjectTypeOut,
    ProjectTypeOverrideUpdate,
    RepresentedPersonaOut,
    RepresentsCreate,
    StakeholderCommentCreate,
    StakeholderCommentOut,
    StakeholderCommentUpdate,
    StakeholderCreate,
    StakeholderFromUserCreate,
    StakeholderOut,
    StakeholderTransitionRequest,
    StakeholderUpdate,
    StakeholderVersionOut,
    VisibilitySet,
)
from app.modules.stakeholders.service import (
    STAKEHOLDER_ARTEFACT_TYPE,
    STAKEHOLDER_TYPES,
    archive_record,
    clear_project_stakeholder_visibility,
    delete_represents_link,
    get_current_stakeholder_version,
    grid_quadrant,
    hidden_persona_ids,
    hidden_stakeholder_ids,
    list_project_visible_stakeholders,
    list_represented_personas,
    list_representing_stakeholders,
    set_project_stakeholder_visibility,
    suggest_cadence,
    unarchive_record,
)
from app.schemas.file import FileAssetOut
from app.services.audit import log_event
from app.services.rbac import require_project_subcomponent_enabled

router = APIRouter(prefix="/api/v1/projects/{project_id}/modules/stakeholders", tags=["stakeholders-project"])

_SCOPE = StakeholderScope.PROJECT
_require_view = require_project_subcomponent_enabled("stakeholders", "stakeholder")


def _project(db: Session, project_id: UUID) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found.")
    return project


def _get(db: Session, project_id: UUID, stakeholder_id: UUID) -> Stakeholder:
    """A project-scoped stakeholder of this project (404 for anything else)."""
    return sh.get_stakeholder_in_scope(db, _SCOPE, project_id=project_id, stakeholder_id=stakeholder_id)


def _is_visible(stakeholder: Stakeholder, project: Project, hidden: set[UUID]) -> bool:
    """Whether `project` can see `stakeholder`; `hidden` is `hidden_stakeholder_ids` for the project."""
    return (
        (stakeholder.scope == StakeholderScope.PROJECT and stakeholder.project_id == project.id)
        or (stakeholder.scope == StakeholderScope.ORGANIZATION and stakeholder.organization_id == project.organization_id
            and stakeholder.id not in hidden)
    )


def _require_manage(db: Session, user: User, project: Project) -> None:
    sh.require_stakeholder_manage(db, user, _SCOPE, organization_id=project.organization_id, project_id=project.id)


def _out(db: Session, stakeholder: Stakeholder, project_id: UUID | None = None) -> StakeholderOut:
    return sh.stakeholder_to_out(
        db, stakeholder, get_current_stakeholder_version(db, stakeholder.id), project_id=project_id
    )


# --- Stakeholder type vocabulary (project half) ------------------------------


@router.get("/stakeholder-types", response_model=list[EffectiveTypeOut])
def list_project_stakeholder_types(project_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db)):
    """The project's effective Stakeholder type list (org types with
    overrides applied, plus project-local ones). Open to any project member so
    a type picker can be populated."""
    project = _project(db, project_id)
    return STAKEHOLDER_TYPES.resolve_effective(db, project_id, project.organization_id)


@router.post("/stakeholder-types", response_model=ProjectTypeOut, status_code=status.HTTP_201_CREATED)
def create_project_local_stakeholder_type(
    project_id: UUID, payload: ProjectTypeCreate, current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    project = _project(db, project_id)
    _require_manage(db, current_user, project)
    try:
        row = STAKEHOLDER_TYPES.create_project_local(db, project_id, payload.name, display_order=payload.display_order)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    log_event(db, entity_type="project_stakeholder_type", entity_id=row.id, action="created", actor_id=current_user.id,
              project_id=project_id, detail={"name": payload.name})
    db.commit()
    db.refresh(row)
    return row


@router.put("/stakeholder-types/{type_ref_id}", response_model=ProjectTypeOut)
def override_project_stakeholder_type(
    project_id: UUID, type_ref_id: UUID, payload: ProjectTypeOverrideUpdate,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Partial override of a type here. `type_ref_id` is an
    `EffectiveTypeOut.id`: an org type gets its override row on first use."""
    project = _project(db, project_id)
    _require_manage(db, current_user, project)
    try:
        row = STAKEHOLDER_TYPES.get_or_create_project_type(db, project_id, project.organization_id, type_ref_id)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    STAKEHOLDER_TYPES.set_override(
        db, row, name=payload.name, display_order=payload.display_order, is_enabled=payload.is_enabled
    )
    log_event(db, entity_type="project_stakeholder_type", entity_id=row.id, action="updated",
              actor_id=current_user.id, project_id=project_id)
    db.commit()
    db.refresh(row)
    return row


@router.delete("/stakeholder-types/{project_type_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project_stakeholder_type(
    project_id: UUID, project_type_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Removes a project type row (an override reverts to the org default);
    409 while a stakeholder still uses it."""
    project = _project(db, project_id)
    _require_manage(db, current_user, project)
    row = db.get(ProjectStakeholderType, project_type_id)
    if row is None or row.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Stakeholder type not found.")
    psh.apply_value_error_as_conflict(STAKEHOLDER_TYPES.delete_project_type, db, row)
    log_event(db, entity_type="project_stakeholder_type", entity_id=project_type_id, action="deleted",
              actor_id=current_user.id, project_id=project_id)
    db.commit()


# --- Cadence hint ------------------------------------------------------------


@router.get("/stakeholders/cadence-hint", response_model=CadenceHintOut)
def get_cadence_hint(
    project_id: UUID, influence_level_id: UUID | None = None, interest_level_id: UUID | None = None,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """The power/interest quadrant and suggested cadence for a pair of levels
    (resolution 21); a hint only. Declared before `/stakeholders/{id}` so the
    literal path wins."""
    project = _project(db, project_id)
    try:
        quadrant = grid_quadrant(
            db, project.organization_id, influence_level_id=influence_level_id, interest_level_id=interest_level_id
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return CadenceHintOut(quadrant=quadrant, suggested_cadence=suggest_cadence(quadrant))


# --- Stakeholder CRUD --------------------------------------------------------


@router.post("/stakeholders", response_model=StakeholderOut, status_code=status.HTTP_201_CREATED)
def create_project_stakeholder(
    project_id: UUID, payload: StakeholderCreate, current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Creates a project-scoped stakeholder in `DRAFT`. Requires the
    stakeholder owner role (or FGAC grant)."""
    project = _project(db, project_id)
    _require_manage(db, current_user, project)
    return sh.create_stakeholder_from_payload(
        db, _SCOPE, payload, current_user, organization_id=project.organization_id, project_id=project_id,
    )


@router.post("/stakeholders/from-user", response_model=StakeholderOut, status_code=status.HTTP_201_CREATED)
def create_project_stakeholder_from_user(
    project_id: UUID, payload: StakeholderFromUserCreate,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Creates a project-scoped stakeholder from an org user (name and contact
    prefilled); 409 if one already represents them."""
    project = _project(db, project_id)
    _require_manage(db, current_user, project)
    return sh.create_stakeholder_from_user(
        db, _SCOPE, payload, current_user, organization_id=project.organization_id, project_id=project_id,
    )


@router.get("/stakeholders", response_model=list[StakeholderOut])
def list_project_stakeholders(
    project_id: UUID, include_archived: bool = False, include_org: bool = True, include_hidden: bool = False,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """The project's stakeholders, plus the organisation's unless
    `include_org=false`. Org stakeholders hidden from the project are left out
    unless `include_hidden=true` (the manage UI), where they carry `project_hidden`."""
    project = _project(db, project_id)
    stakeholders = list_project_visible_stakeholders(
        db, project, include_archived=include_archived, include_hidden=include_hidden
    )
    if not include_org:
        stakeholders = [s for s in stakeholders if s.scope == StakeholderScope.PROJECT]
    return [_out(db, s, project_id) for s in stakeholders]


@router.get("/stakeholders/{stakeholder_id}", response_model=StakeholderOut)
def get_project_stakeholder(
    project_id: UUID, stakeholder_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    return _out(db, get_visible_stakeholder(db, _project(db, project_id), stakeholder_id), project_id)


# --- Visibility override (hide an org stakeholder from this project) ----------


def _get_org_stakeholder(db: Session, project: Project, stakeholder_id: UUID) -> Stakeholder:
    """An org stakeholder of the project's organisation, hidden or not (404 otherwise)."""
    return sh.get_stakeholder_in_scope(
        db, StakeholderScope.ORGANIZATION, organization_id=project.organization_id, stakeholder_id=stakeholder_id
    )


@router.put("/stakeholders/{stakeholder_id}/visibility", response_model=StakeholderOut)
def set_project_stakeholder_visibility_endpoint(
    project_id: UUID, stakeholder_id: UUID, payload: VisibilitySet,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Hides an org stakeholder from this project (`hidden=true`) or, if a
    parent project hides it, shows it again here (`hidden=false`). Writes only
    this project's override; the shared record, its links and needs are untouched."""
    project = _project(db, project_id)
    stakeholder = _get_org_stakeholder(db, project, stakeholder_id)
    _require_manage(db, current_user, project)
    psh.apply_value_error_as_conflict(set_project_stakeholder_visibility, db, project, stakeholder, payload.hidden)
    log_event(db, entity_type=STAKEHOLDER_ARTEFACT_TYPE, entity_id=stakeholder.id,
              action="visibility_hidden" if payload.hidden else "visibility_shown", actor_id=current_user.id,
              project_id=project_id)
    db.commit()
    return _out(db, stakeholder, project_id)


@router.delete("/stakeholders/{stakeholder_id}/visibility", response_model=StakeholderOut)
def clear_project_stakeholder_visibility_endpoint(
    project_id: UUID, stakeholder_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Removes this project's own override, reverting to the inherited (else visible) state."""
    project = _project(db, project_id)
    stakeholder = _get_org_stakeholder(db, project, stakeholder_id)
    _require_manage(db, current_user, project)
    if clear_project_stakeholder_visibility(db, project_id, stakeholder.id):
        log_event(db, entity_type=STAKEHOLDER_ARTEFACT_TYPE, entity_id=stakeholder.id, action="visibility_reset",
                  actor_id=current_user.id, project_id=project_id)
    db.commit()
    return _out(db, stakeholder, project_id)


@router.put("/stakeholders/{stakeholder_id}", response_model=StakeholderOut)
def update_project_stakeholder(
    project_id: UUID, stakeholder_id: UUID, payload: StakeholderUpdate,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    project = _project(db, project_id)
    stakeholder = _get(db, project_id, stakeholder_id)
    _require_manage(db, current_user, project)
    return sh.update_stakeholder_from_payload(
        db, stakeholder, payload, current_user, organization_id=project.organization_id, project_id=project_id,
    )


@router.get("/stakeholders/{stakeholder_id}/versions", response_model=list[StakeholderVersionOut])
def list_project_stakeholder_versions(
    project_id: UUID, stakeholder_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    return get_visible_stakeholder(db, _project(db, project_id), stakeholder_id).versions


@router.delete("/stakeholders/{stakeholder_id}", status_code=status.HTTP_204_NO_CONTENT)
def erase_project_stakeholder(
    project_id: UUID, stakeholder_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Permanently deletes a stakeholder and every row/file/link holding data
    about them (Phase 0 resolution 15). Irreversible; the audit event keeps
    only the id."""
    project = _project(db, project_id)
    stakeholder = _get(db, project_id, stakeholder_id)
    _require_manage(db, current_user, project)
    sh.erase_stakeholder_endpoint(db, stakeholder, current_user)


@router.post("/stakeholders/{stakeholder_id}/archive", response_model=StakeholderOut)
def archive_project_stakeholder(
    project_id: UUID, stakeholder_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    project = _project(db, project_id)
    stakeholder = _get(db, project_id, stakeholder_id)
    _require_manage(db, current_user, project)
    archive_record(db, stakeholder, current_user)
    log_event(db, entity_type=STAKEHOLDER_ARTEFACT_TYPE, entity_id=stakeholder.id, action="archived",
              actor_id=current_user.id, project_id=project_id)
    db.commit()
    return _out(db, stakeholder)


@router.post("/stakeholders/{stakeholder_id}/unarchive", response_model=StakeholderOut)
def unarchive_project_stakeholder(
    project_id: UUID, stakeholder_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    project = _project(db, project_id)
    stakeholder = _get(db, project_id, stakeholder_id)
    _require_manage(db, current_user, project)
    unarchive_record(db, stakeholder)
    log_event(db, entity_type=STAKEHOLDER_ARTEFACT_TYPE, entity_id=stakeholder.id, action="unarchived",
              actor_id=current_user.id, project_id=project_id)
    db.commit()
    return _out(db, stakeholder)


@router.post("/stakeholders/{stakeholder_id}/activate", response_model=StakeholderOut)
def activate_project_stakeholder(
    project_id: UUID, stakeholder_id: UUID, payload: StakeholderTransitionRequest | None = None,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """`DRAFT`/`RETIRED` -> `ACTIVE`."""
    project = _project(db, project_id)
    stakeholder = _get(db, project_id, stakeholder_id)
    _require_manage(db, current_user, project)
    return sh.transition_stakeholder_endpoint(
        db, stakeholder, StakeholderStatus.ACTIVE, current_user, action="activated",
        comment=payload.comment if payload else None,
    )


@router.post("/stakeholders/{stakeholder_id}/retire", response_model=StakeholderOut)
def retire_project_stakeholder(
    project_id: UUID, stakeholder_id: UUID, payload: StakeholderTransitionRequest | None = None,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """`DRAFT`/`ACTIVE` -> `RETIRED`."""
    project = _project(db, project_id)
    stakeholder = _get(db, project_id, stakeholder_id)
    _require_manage(db, current_user, project)
    return sh.transition_stakeholder_endpoint(
        db, stakeholder, StakeholderStatus.RETIRED, current_user, action="retired",
        comment=payload.comment if payload else None,
    )


# --- Represents Persona ------------------------------------------------------


@router.get("/stakeholders/{stakeholder_id}/personas", response_model=list[RepresentedPersonaOut])
def list_project_stakeholder_personas(
    project_id: UUID, stakeholder_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """The Personas this stakeholder represents that this project can see
    (its own and the organisation's, minus org ones hidden from the project)."""
    project = _project(db, project_id)
    stakeholder = get_visible_stakeholder(db, project, stakeholder_id)
    hidden = hidden_persona_ids(db, project_id)
    return [
        sh.represents_to_out(db, link, p)
        for link, p in list_represented_personas(db, stakeholder, project.organization_id)
        if (p.scope == PersonaScope.ORGANIZATION and p.id not in hidden) or p.project_id == project.id
    ]


@router.post("/stakeholders/{stakeholder_id}/personas", response_model=RepresentedPersonaOut, status_code=status.HTTP_201_CREATED)
def add_project_stakeholder_persona(
    project_id: UUID, stakeholder_id: UUID, payload: RepresentsCreate,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Records that this project stakeholder represents a Persona this project
    can see (409 on a duplicate)."""
    project = _project(db, project_id)
    stakeholder = _get(db, project_id, stakeholder_id)
    persona = get_visible_persona(db, project, payload.persona_id)
    _require_manage(db, current_user, project)
    return sh.add_represents(db, stakeholder, persona, current_user, organization_id=project.organization_id)


@router.delete("/stakeholders/{stakeholder_id}/personas/{persona_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_project_stakeholder_persona(
    project_id: UUID, stakeholder_id: UUID, persona_id: UUID,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    project = _project(db, project_id)
    stakeholder = _get(db, project_id, stakeholder_id)
    _require_manage(db, current_user, project)
    for link, persona in list_represented_personas(db, stakeholder, project.organization_id):
        if persona.id == persona_id:
            delete_represents_link(db, link)
            log_event(db, entity_type=STAKEHOLDER_ARTEFACT_TYPE, entity_id=stakeholder.id, action="represents_removed",
                      actor_id=current_user.id, project_id=project_id, detail={"persona_id": str(persona_id)})
            db.commit()
            return
    raise HTTPException(status.HTTP_404_NOT_FOUND, "This Stakeholder does not represent that Persona.")


@router.get("/personas/{persona_id}/stakeholders", response_model=list[RepresentedPersonaOut])
def list_project_persona_stakeholders(
    project_id: UUID, persona_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """The Stakeholders that represent this Persona and that this project can
    see (its own and the organisation's)."""
    project = _project(db, project_id)
    persona = get_visible_persona(db, project, persona_id)
    hidden = hidden_stakeholder_ids(db, project_id)
    return [
        sh.stakeholder_link_to_out(db, link, s)
        for link, s in list_representing_stakeholders(db, persona, project.organization_id)
        if _is_visible(s, project, hidden)
    ]


# --- Comments ----------------------------------------------------------------


@router.post("/stakeholders/{stakeholder_id}/comments", response_model=StakeholderCommentOut, status_code=status.HTTP_201_CREATED)
def add_project_stakeholder_comment(
    project_id: UUID, stakeholder_id: UUID, payload: StakeholderCommentCreate,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    stakeholder = get_visible_stakeholder(db, _project(db, project_id), stakeholder_id)
    return sh.add_comment(db, stakeholder, current_user, payload.body, project_id=project_id)


@router.get("/stakeholders/{stakeholder_id}/comments", response_model=list[StakeholderCommentOut])
def list_project_stakeholder_comments(
    project_id: UUID, stakeholder_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    return sh.list_comments(db, get_visible_stakeholder(db, _project(db, project_id), stakeholder_id))


@router.patch("/stakeholders/{stakeholder_id}/comments/{comment_id}", response_model=StakeholderCommentOut)
def edit_project_stakeholder_comment(
    project_id: UUID, stakeholder_id: UUID, comment_id: UUID, payload: StakeholderCommentUpdate,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    stakeholder = get_visible_stakeholder(db, _project(db, project_id), stakeholder_id)
    return sh.edit_comment(db, stakeholder, comment_id, current_user, payload.body, project_id=project_id)


@router.post("/stakeholders/{stakeholder_id}/comments/{comment_id}/files", response_model=FileAssetOut, status_code=status.HTTP_201_CREATED)
async def upload_project_stakeholder_comment_attachment(
    project_id: UUID, stakeholder_id: UUID, comment_id: UUID, file: UploadFile = File(...),
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    project = _project(db, project_id)
    stakeholder = get_visible_stakeholder(db, project, stakeholder_id)
    return await sh.attach_to_comment(
        db, stakeholder, comment_id, current_user, file, organization_id=project.organization_id,
        project_id=project_id,
    )


@router.delete("/stakeholders/{stakeholder_id}/comments/{comment_id}/files/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_project_stakeholder_comment_attachment(
    project_id: UUID, stakeholder_id: UUID, comment_id: UUID, file_id: UUID,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    stakeholder = get_visible_stakeholder(db, _project(db, project_id), stakeholder_id)
    sh.remove_comment_attachment(db, stakeholder, comment_id, file_id, current_user, project_id=project_id)


# --- Direct files ------------------------------------------------------------


@router.post("/stakeholders/{stakeholder_id}/files", response_model=FileAssetOut, status_code=status.HTTP_201_CREATED)
async def upload_project_stakeholder_file(
    project_id: UUID, stakeholder_id: UUID, file: UploadFile = File(...),
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    project = _project(db, project_id)
    stakeholder = _get(db, project_id, stakeholder_id)
    _require_manage(db, current_user, project)
    return await sh.attach_file(
        db, stakeholder, current_user, file, organization_id=project.organization_id, project_id=project_id
    )


@router.get("/stakeholders/{stakeholder_id}/files", response_model=list[FileAssetOut])
def list_project_stakeholder_files(
    project_id: UUID, stakeholder_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    return sh.list_files(db, get_visible_stakeholder(db, _project(db, project_id), stakeholder_id))


@router.delete("/stakeholders/{stakeholder_id}/files/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
def unlink_project_stakeholder_file(
    project_id: UUID, stakeholder_id: UUID, file_id: UUID,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    project = _project(db, project_id)
    stakeholder = _get(db, project_id, stakeholder_id)
    _require_manage(db, current_user, project)
    sh.unlink_file(db, stakeholder, file_id, current_user, project_id=project_id)
