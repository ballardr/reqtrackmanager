"""
Module: routers.custom_fields

CRUD for per-project custom attribute definitions on requirements and
change requests (C-C-01, C-C-02).
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models.custom_field import CustomFieldDefinition, CustomFieldEntityKind
from app.models.project import Project
from app.models.user import User
from app.schemas.custom_field import CustomFieldDefinitionCreate, CustomFieldDefinitionOut
from app.services.audit import log_event
from app.services.rbac import require_project_manage, require_project_view

router = APIRouter(prefix="/api/v1/projects/{project_id}/custom-fields", tags=["custom-fields"])


@router.post("", response_model=CustomFieldDefinitionOut, status_code=status.HTTP_201_CREATED)
def create_custom_field(
    payload: CustomFieldDefinitionCreate, project: Project = Depends(require_project_manage),
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    count = len(
        db.scalars(
            select(CustomFieldDefinition.id).where(
                CustomFieldDefinition.project_id == project.id, CustomFieldDefinition.entity_kind == payload.entity_kind
            )
        ).all()
    )
    definition = CustomFieldDefinition(
        project_id=project.id, entity_kind=payload.entity_kind, name=payload.name,
        field_type=payload.field_type, options=payload.options, required=payload.required, sort_order=count,
    )
    db.add(definition)
    db.flush()
    log_event(db, entity_type="custom_field_definition", entity_id=definition.id, action="created",
              actor_id=current_user.id, project_id=project.id, organization_id=project.organization_id,
              detail={"name": definition.name, "entity_kind": definition.entity_kind.value})
    db.commit()
    db.refresh(definition)
    return definition


@router.get("", response_model=list[CustomFieldDefinitionOut])
def list_custom_fields(
    project_id: UUID, entity_kind: CustomFieldEntityKind | None = None,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    query = select(CustomFieldDefinition).where(CustomFieldDefinition.project_id == project_id)
    if entity_kind is not None:
        query = query.where(CustomFieldDefinition.entity_kind == entity_kind)
    return db.scalars(query.order_by(CustomFieldDefinition.sort_order)).all()


@router.delete("/{field_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_custom_field(
    field_id: UUID, project: Project = Depends(require_project_manage),
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    """Deletes a custom field definition. Historical values already stored on
    past requirement/CR versions are preserved (they're just JSONB data,
    unaffected by the definition's lifecycle)."""
    definition = db.get(CustomFieldDefinition, field_id)
    if definition is None or definition.project_id != project.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Custom field not found.")
    log_event(db, entity_type="custom_field_definition", entity_id=definition.id, action="deleted",
              actor_id=current_user.id, project_id=project.id, organization_id=project.organization_id,
              detail={"name": definition.name})
    db.delete(definition)
    db.commit()
