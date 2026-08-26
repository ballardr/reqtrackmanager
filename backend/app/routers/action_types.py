"""
Module: routers.action_types

CRUD for project-scoped requirement-action type definitions
(`ActionTypeDefinition`) — mirrors `routers.custom_fields`'s shape
(`require_project_manage` for writes, `require_project_view` for list),
plus the shared rename/reorder/delete-with-reassignment rules described in
`services.definitions`' module docstring (identical contract to the
org-scoped project-statuses/link-types sections in `routers.orgs`, just
scoped to a project instead of an organisation).
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models.action_type import ActionTypeDefinition
from app.models.project import Project
from app.models.requirement_action import RequirementAction
from app.models.user import User
from app.schemas.action_type import ActionTypeCreate, ActionTypeOut, ActionTypeUpdate
from app.schemas.project import MoveDirection
from app.services.audit import log_event
from app.services.definitions import delete_definition_with_reassignment
from app.services.ordering import move_ordered
from app.services.project_hierarchy import resolve_effective_action_types
from app.services.rbac import require_project_manage, require_project_view

router = APIRouter(prefix="/api/v1/projects/{project_id}/action-types", tags=["action-types"])


@router.post("", response_model=ActionTypeOut, status_code=status.HTTP_201_CREATED)
def create_action_type(
    payload: ActionTypeCreate, project: Project = Depends(require_project_manage),
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    """Creates a new action type in this project (C-C-01-style admin list,
    scoped to the project — see `models.action_type`'s docstring for why
    action types are project-scoped rather than org-scoped)."""
    existing = db.scalar(
        select(ActionTypeDefinition.id).where(
            ActionTypeDefinition.project_id == project.id, ActionTypeDefinition.name == payload.name
        )
    )
    if existing is not None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "An action type with this name already exists.")
    count = len(db.scalars(select(ActionTypeDefinition.id).where(ActionTypeDefinition.project_id == project.id)).all())
    action_type = ActionTypeDefinition(project_id=project.id, name=payload.name, sort_order=count)
    db.add(action_type)
    db.flush()
    log_event(db, entity_type="action_type_definition", entity_id=action_type.id, action="created",
              actor_id=current_user.id, project_id=project.id, organization_id=project.organization_id,
              detail={"name": action_type.name})
    db.commit()
    db.refresh(action_type)
    return action_type


@router.get("", response_model=list[ActionTypeOut])
def list_action_types(
    project_id: UUID, current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    """Lists a project's action types — any project member may select one
    when creating an action, so listing isn't manage-only (only
    create/rename/move/delete are). A project with none of its own falls
    back to its nearest ancestor's (hierarchical projects, always on
    independent of RBAC inheritance settings — see
    `services.project_hierarchy.resolve_effective_action_types`)."""
    return resolve_effective_action_types(db, project_id)


@router.post("/{action_type_id}/move", response_model=ActionTypeOut)
def move_action_type(
    project_id: UUID, action_type_id: UUID, payload: MoveDirection,
    project: Project = Depends(require_project_manage), current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Moves an action type up/down in display order."""
    result = move_ordered(db, ActionTypeDefinition, [ActionTypeDefinition.project_id == project.id], action_type_id, payload.direction)
    log_event(db, entity_type="action_type_definition", entity_id=action_type_id, action="reordered",
              actor_id=current_user.id, project_id=project.id, organization_id=project.organization_id,
              detail={"direction": payload.direction})
    db.commit()
    return result


@router.patch("/{action_type_id}", response_model=ActionTypeOut)
def rename_action_type(
    project_id: UUID, action_type_id: UUID, payload: ActionTypeUpdate,
    project: Project = Depends(require_project_manage), current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Renames an action type. Every `RequirementAction.action_type_id`
    reference points at this row's id, never its name, so renaming has zero
    effect on existing actions — see `services.definitions`' module
    docstring."""
    action_type = db.get(ActionTypeDefinition, action_type_id)
    if action_type is None or action_type.project_id != project.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Action type not found.")
    existing = db.scalar(
        select(ActionTypeDefinition.id).where(
            ActionTypeDefinition.project_id == project.id, ActionTypeDefinition.name == payload.name,
            ActionTypeDefinition.id != action_type_id,
        )
    )
    if existing is not None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "An action type with this name already exists.")
    action_type.name = payload.name
    log_event(db, entity_type="action_type_definition", entity_id=action_type.id, action="renamed",
              actor_id=current_user.id, project_id=project.id, organization_id=project.organization_id)
    db.commit()
    db.refresh(action_type)
    return action_type


@router.delete("/{action_type_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_action_type(
    project_id: UUID, action_type_id: UUID, reassign_to_id: UUID | None = Query(None),
    project: Project = Depends(require_project_manage), current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Deletes an action type, applying the shared rename/delete/reassign
    rules (§4.0): refuses to leave a *root* project with zero action types
    (409) — a project with a parent may always be emptied of its own,
    since it falls back to its nearest ancestor's
    (`services.project_hierarchy.resolve_effective_action_types`) — and
    requires an explicit `reassign_to_id` to delete a type that's currently
    in use by any `RequirementAction` (409 naming the count if omitted;
    bulk-reassigns then deletes if provided) — see
    `services.definitions.delete_definition_with_reassignment`'s docstring
    for the exact behaviour.
    """
    delete_definition_with_reassignment(
        db, definition_model=ActionTypeDefinition, scope_column=ActionTypeDefinition.project_id, scope_id=project.id,
        item_id=action_type_id, reassign_to_id=reassign_to_id,
        referencing_model=RequirementAction, referencing_fk_column=RequirementAction.action_type_id,
        referencing_fk_name="action_type_id", entity_type="action_type_definition", noun="action type",
        plural_noun="action(s)", reassign_verb="move",
        min_count_message="A project must always have at least one action type.",
        actor_id=current_user.id, organization_id=project.organization_id, project_id=project.id,
        allow_empty=project.parent_project_id is not None,
    )
    db.commit()
