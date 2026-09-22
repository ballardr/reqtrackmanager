"""
Module: routers.requirements.actions

Requirement<->action linking (see `models.requirement_action`). A
`RequirementAction` has its own project-scoped identity (`routers.actions`)
so it can be linked from multiple requirements; these four endpoints are
the requirement-side half of that many-to-many relationship, each gated by
the same creation-or-change-request-only rule as every other requirement
content field once it's locked (C-G-12).
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.action_type import ActionTypeDefinition
from app.models.enums import ArtefactType
from app.models.project import Project
from app.models.requirement_action import RequirementAction
from app.models.user import User
from app.routers.requirements.core import _get_requirement_in_project, _require_edit_role
from app.schemas.action import RequirementActionCreate, RequirementActionLinkCreate, RequirementActionOut
from app.services.actions import action_to_out, generate_unique_code, get_requirement_action_in_project
from app.services.audit import log_event
from app.services.rbac import require_project_view
from app.services.relationships import create_link as create_artefact_link
from app.services.relationships import delete_link as delete_artefact_link
from app.services.relationships import get_all_links as get_all_artefact_links
from app.services.relationships import get_link_between as get_artefact_link_between
from app.services.requirements import get_current_version, is_locked

router = APIRouter(tags=["requirements-actions"])


@router.post("/{requirement_id}/actions", status_code=status.HTTP_204_NO_CONTENT)
def link_action(
    project_id: UUID, requirement_id: UUID, payload: RequirementActionLinkCreate,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    """Links an existing action to this requirement. Unlike `create_link`
    (requirement-to-requirement, in `routers.requirements.links`), linking
    an action isn't itself content with a display direction — just
    membership in the action's "which requirements does this satisfy"
    set — so this returns no body.

    Governed by the same creation-or-change-request-only rule as every
    other requirement content once it's locked (C-G-12) — see
    `routers.requirements.files.upload_requirement_attachment`'s docstring.
    2026-08 UX audit roadmap item 514: this endpoint previously had no lock
    check at all, unlike the requirement's own fields, letting an action
    bypass the change-request-only rule entirely once approved.
    """
    _require_edit_role(db, current_user, project_id)
    requirement = _get_requirement_in_project(db, project_id, requirement_id)
    if is_locked(get_current_version(db, requirement.id)):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This requirement is approved; actions can only be added via a change request.",
        )
    action = get_requirement_action_in_project(db, project_id, payload.action_id)
    existing = get_artefact_link_between(
        db, source_type=ArtefactType.REQUIREMENT_ACTION, source_id=action.id,
        target_type=ArtefactType.REQUIREMENT, target_id=requirement_id,
    )
    if existing is not None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This action is already linked to this requirement.")
    create_artefact_link(
        db, source_type=ArtefactType.REQUIREMENT_ACTION, source_id=action.id,
        target_type=ArtefactType.REQUIREMENT, target_id=requirement_id,
        link_type_id=None, created_by=current_user.id,
    )
    log_event(db, entity_type="requirement_action_link", entity_id=action.id, action="linked",
              actor_id=current_user.id, project_id=project_id,
              detail={"requirement_id": str(requirement_id), "action_id": str(action.id)})
    db.commit()


@router.post(
    "/{requirement_id}/actions/create-and-link", response_model=RequirementActionOut, status_code=status.HTTP_201_CREATED
)
def create_and_link_action(
    project_id: UUID, requirement_id: UUID, payload: RequirementActionCreate,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    """Creates a new action and links it to this requirement in one
    transaction — avoids a two-request create-then-link race in the
    inline-create UI (create the action, then have the very next `POST
    .../actions` fail or double-submit).

    Same lock rule as `link_action`, above — see its docstring.
    """
    _require_edit_role(db, current_user, project_id)
    requirement = _get_requirement_in_project(db, project_id, requirement_id)
    if is_locked(get_current_version(db, requirement.id)):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This requirement is approved; actions can only be added via a change request.",
        )
    project = db.get(Project, project_id)
    action_type = db.get(ActionTypeDefinition, payload.action_type_id)
    if action_type is None or action_type.project_id != project_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "action_type_id must be an action type defined in this project.")
    action = RequirementAction(
        project_id=project_id, unique_code=generate_unique_code(project), action_type_id=payload.action_type_id,
        title=payload.title, description=payload.description, assignee_id=payload.assignee_id,
        due_date=payload.due_date, creator_id=current_user.id,
    )
    db.add(action)
    db.flush()
    create_artefact_link(
        db, source_type=ArtefactType.REQUIREMENT_ACTION, source_id=action.id,
        target_type=ArtefactType.REQUIREMENT, target_id=requirement_id,
        link_type_id=None, created_by=current_user.id,
    )
    log_event(db, entity_type="requirement_action", entity_id=action.id, action="created",
              actor_id=current_user.id, project_id=project_id, organization_id=project.organization_id,
              detail={"unique_code": action.unique_code, "title": action.title, "linked_requirement_id": str(requirement_id)})
    db.commit()
    db.refresh(action)
    return action_to_out(db, action)


@router.get("/{requirement_id}/actions", response_model=list[RequirementActionOut])
def list_requirement_actions(
    project_id: UUID, requirement_id: UUID,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    """Lists every action linked to this requirement."""
    _get_requirement_in_project(db, project_id, requirement_id)
    action_ids = [
        link.source_id
        for link in get_all_artefact_links(db, ArtefactType.REQUIREMENT, requirement_id)
        if link.source_type == ArtefactType.REQUIREMENT_ACTION
    ]
    if not action_ids:
        return []
    actions = db.scalars(
        select(RequirementAction).where(RequirementAction.id.in_(action_ids)).order_by(RequirementAction.unique_code)
    ).all()
    return [action_to_out(db, a) for a in actions]


@router.delete("/{requirement_id}/actions/{action_id}", status_code=status.HTTP_204_NO_CONTENT)
def unlink_action(
    project_id: UUID, requirement_id: UUID, action_id: UUID,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    """Unlinks an action from this requirement — never deletes the action
    itself, which may still be linked from other requirements.

    Governed by the same creation-or-change-request-only rule as
    `link_action`/`create_and_link_action`, above (C-G-12) — Platform
    review 2026-09, Phase 8: this endpoint previously had no lock check at
    all, an asymmetry with the *add* side (which has been gated since item
    514) that let an action be silently unlinked from an approved
    requirement with no review step. Unconditional across every project —
    unlike the traceability-link gate in `routers.requirements.links`, this
    doesn't depend on any project/org opt-in.
    """
    _require_edit_role(db, current_user, project_id)
    requirement = _get_requirement_in_project(db, project_id, requirement_id)
    if is_locked(get_current_version(db, requirement.id)):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This requirement is approved; actions can only be removed via a change request.",
        )
    link = get_artefact_link_between(
        db, source_type=ArtefactType.REQUIREMENT_ACTION, source_id=action_id,
        target_type=ArtefactType.REQUIREMENT, target_id=requirement_id,
    )
    if link is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This action is not linked to this requirement.")
    log_event(db, entity_type="requirement_action_link", entity_id=action_id, action="unlinked",
              actor_id=current_user.id, project_id=project_id,
              detail={"requirement_id": str(requirement_id), "action_id": str(action_id)})
    delete_artefact_link(db, link)
    db.commit()
