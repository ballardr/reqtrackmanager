"""
Module: modules.compliance.router.action_types

This organisation's extensible required-action-type vocabulary:
create/list/reorder/rename/delete (delete-with-reassignment via
`services.definitions`).
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.modules.compliance.models import ComplianceActionTypeDefinition, ComplianceRequiredAction
from app.modules.compliance.router._shared import _require_manage, _require_view
from app.modules.compliance.schemas import ComplianceActionTypeCreate, ComplianceActionTypeOut, ComplianceActionTypeUpdate
from app.schemas.project import MoveDirection
from app.services.audit import log_event
from app.services.definitions import delete_definition_with_reassignment
from app.services.ordering import move_ordered

router = APIRouter(tags=["compliance-org-action-types"])


@router.post("/action-types", response_model=ComplianceActionTypeOut, status_code=status.HTTP_201_CREATED)
def create_action_type(
    organization_id: UUID, payload: ComplianceActionTypeCreate,
    current_user: User = Depends(_require_manage), db: Session = Depends(get_db),
):
    """Creates a new organisation-scoped required-action type (§6)."""
    existing = db.scalar(
        select(ComplianceActionTypeDefinition.id).where(
            ComplianceActionTypeDefinition.organization_id == organization_id,
            ComplianceActionTypeDefinition.name == payload.name,
        )
    )
    if existing is not None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "An action type with this name already exists.")
    count = len(
        db.scalars(
            select(ComplianceActionTypeDefinition.id).where(
                ComplianceActionTypeDefinition.organization_id == organization_id
            )
        ).all()
    )
    action_type = ComplianceActionTypeDefinition(organization_id=organization_id, name=payload.name, sort_order=count)
    db.add(action_type)
    db.flush()
    log_event(db, entity_type="compliance_action_type_definition", entity_id=action_type.id, action="created",
              actor_id=current_user.id, organization_id=organization_id, detail={"name": action_type.name})
    db.commit()
    db.refresh(action_type)
    return action_type


@router.get("/action-types", response_model=list[ComplianceActionTypeOut])
def list_action_types(
    organization_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Lists this organisation's required-action types — any org member
    with the module enabled may select one when authoring a required
    action, so listing isn't manage-only."""
    return db.scalars(
        select(ComplianceActionTypeDefinition)
        .where(ComplianceActionTypeDefinition.organization_id == organization_id)
        .order_by(ComplianceActionTypeDefinition.sort_order)
    ).all()


@router.post("/action-types/{action_type_id}/move", response_model=ComplianceActionTypeOut)
def move_action_type(
    organization_id: UUID, action_type_id: UUID, payload: MoveDirection,
    current_user: User = Depends(_require_manage), db: Session = Depends(get_db),
):
    """Moves an action type up/down in display order."""
    result = move_ordered(
        db, ComplianceActionTypeDefinition,
        [ComplianceActionTypeDefinition.organization_id == organization_id], action_type_id, payload.direction,
    )
    log_event(db, entity_type="compliance_action_type_definition", entity_id=action_type_id, action="reordered",
              actor_id=current_user.id, organization_id=organization_id, detail={"direction": payload.direction})
    db.commit()
    return result


@router.patch("/action-types/{action_type_id}", response_model=ComplianceActionTypeOut)
def rename_action_type(
    organization_id: UUID, action_type_id: UUID, payload: ComplianceActionTypeUpdate,
    current_user: User = Depends(_require_manage), db: Session = Depends(get_db),
):
    """Renames an action type. Every `ComplianceRequiredAction.
    action_type_id` reference points at this row's id, never its name, so
    renaming has zero effect on existing required actions."""
    action_type = db.get(ComplianceActionTypeDefinition, action_type_id)
    if action_type is None or action_type.organization_id != organization_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Action type not found.")
    existing = db.scalar(
        select(ComplianceActionTypeDefinition.id).where(
            ComplianceActionTypeDefinition.organization_id == organization_id,
            ComplianceActionTypeDefinition.name == payload.name,
            ComplianceActionTypeDefinition.id != action_type_id,
        )
    )
    if existing is not None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "An action type with this name already exists.")
    action_type.name = payload.name
    log_event(db, entity_type="compliance_action_type_definition", entity_id=action_type.id, action="renamed",
              actor_id=current_user.id, organization_id=organization_id)
    db.commit()
    db.refresh(action_type)
    return action_type


@router.delete("/action-types/{action_type_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_action_type(
    organization_id: UUID, action_type_id: UUID, reassign_to_id: UUID | None = Query(None),
    current_user: User = Depends(_require_manage), db: Session = Depends(get_db),
):
    """Deletes an organisation-scoped action type, applying the shared
    rename/delete/reassign rules (`services.definitions`). Unlike project-
    scoped `ActionTypeDefinition`, there is no "must always retain at least
    one" floor here — an organisation's compliance action-type vocabulary
    may be emptied to zero (§6 doesn't require a non-empty minimum the way
    a project's requirement-action-type picker does), so `allow_empty=True`
    unconditionally. Requires an explicit `reassign_to_id` to delete a type
    currently in use by any `ComplianceRequiredAction` (409 naming the
    count if omitted; bulk-reassigns then deletes if provided)."""
    delete_definition_with_reassignment(
        db, definition_model=ComplianceActionTypeDefinition,
        scope_column=ComplianceActionTypeDefinition.organization_id, scope_id=organization_id,
        item_id=action_type_id, reassign_to_id=reassign_to_id,
        referencing_model=ComplianceRequiredAction, referencing_fk_column=ComplianceRequiredAction.action_type_id,
        referencing_fk_name="action_type_id", entity_type="compliance_action_type_definition", noun="action type",
        plural_noun="required action(s)", reassign_verb="move",
        min_count_message="",  # unreachable: allow_empty=True skips the floor check that would use this
        actor_id=current_user.id, organization_id=organization_id, project_id=None,
        allow_empty=True,
    )
    db.commit()
