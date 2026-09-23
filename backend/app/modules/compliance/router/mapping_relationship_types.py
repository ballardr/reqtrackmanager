"""
Module: modules.compliance.router.mapping_relationship_types

This organisation's extensible cross-standard mapping-relationship-
type vocabulary (Phase 11, §19/§27): create/list/reorder/update/delete
(delete-with-reassignment) — mirrors `action_types.py` exactly.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.modules.compliance.models import ComplianceMappingRelationshipTypeDefinition, ComplianceRequirementMapping
from app.modules.compliance.router._shared import _require_manage, _require_view
from app.modules.compliance.schemas import (
    ComplianceMappingRelationshipTypeCreate,
    ComplianceMappingRelationshipTypeOut,
    ComplianceMappingRelationshipTypeUpdate,
)
from app.schemas.project import MoveDirection
from app.services.audit import log_event
from app.services.definitions import delete_definition_with_reassignment
from app.services.ordering import move_ordered

router = APIRouter(tags=["compliance-org-mapping-relationship-types"])


@router.post(
    "/mapping-relationship-types", response_model=ComplianceMappingRelationshipTypeOut,
    status_code=status.HTTP_201_CREATED,
)
def create_mapping_relationship_type(
    organization_id: UUID, payload: ComplianceMappingRelationshipTypeCreate,
    current_user: User = Depends(_require_manage), db: Session = Depends(get_db),
):
    """Creates a new organisation-scoped cross-standard-mapping
    relationship type (§19's "configurable or extensible" relationship
    vocabulary — Equivalent/Satisfies/Derived From/Related To/Overlaps/
    Conflicts With are examples to seed later, Phase 15, not a fixed set).
    Mirrors `create_action_type`, extended with `implies_equivalence`
    (default `False`) — see `models.py`'s own Phase 11 notes for what this
    flag gates (whether a `replaced` version-diff pair linked by this type
    may ever be offered for migration carry-forward)."""
    existing = db.scalar(
        select(ComplianceMappingRelationshipTypeDefinition.id).where(
            ComplianceMappingRelationshipTypeDefinition.organization_id == organization_id,
            ComplianceMappingRelationshipTypeDefinition.name == payload.name,
        )
    )
    if existing is not None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A relationship type with this name already exists.")
    count = len(
        db.scalars(
            select(ComplianceMappingRelationshipTypeDefinition.id).where(
                ComplianceMappingRelationshipTypeDefinition.organization_id == organization_id
            )
        ).all()
    )
    relationship_type = ComplianceMappingRelationshipTypeDefinition(
        organization_id=organization_id, name=payload.name, sort_order=count,
        implies_equivalence=payload.implies_equivalence,
    )
    db.add(relationship_type)
    db.flush()
    log_event(db, entity_type="compliance_mapping_relationship_type", entity_id=relationship_type.id, action="created",
              actor_id=current_user.id, organization_id=organization_id,
              detail={"name": relationship_type.name, "implies_equivalence": relationship_type.implies_equivalence})
    db.commit()
    db.refresh(relationship_type)
    return relationship_type


@router.get("/mapping-relationship-types", response_model=list[ComplianceMappingRelationshipTypeOut])
def list_mapping_relationship_types(
    organization_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Lists this organisation's cross-standard-mapping relationship
    types — any org member with the module enabled may select one when
    creating a mapping, so listing isn't manage-only, mirroring
    `list_action_types`."""
    return db.scalars(
        select(ComplianceMappingRelationshipTypeDefinition)
        .where(ComplianceMappingRelationshipTypeDefinition.organization_id == organization_id)
        .order_by(ComplianceMappingRelationshipTypeDefinition.sort_order)
    ).all()


@router.post("/mapping-relationship-types/{relationship_type_id}/move", response_model=ComplianceMappingRelationshipTypeOut)
def move_mapping_relationship_type(
    organization_id: UUID, relationship_type_id: UUID, payload: MoveDirection,
    current_user: User = Depends(_require_manage), db: Session = Depends(get_db),
):
    """Moves a relationship type up/down in display order."""
    result = move_ordered(
        db, ComplianceMappingRelationshipTypeDefinition,
        [ComplianceMappingRelationshipTypeDefinition.organization_id == organization_id],
        relationship_type_id, payload.direction,
    )
    log_event(db, entity_type="compliance_mapping_relationship_type", entity_id=relationship_type_id, action="reordered",
              actor_id=current_user.id, organization_id=organization_id, detail={"direction": payload.direction})
    db.commit()
    return result


@router.patch("/mapping-relationship-types/{relationship_type_id}", response_model=ComplianceMappingRelationshipTypeOut)
def update_mapping_relationship_type(
    organization_id: UUID, relationship_type_id: UUID, payload: ComplianceMappingRelationshipTypeUpdate,
    current_user: User = Depends(_require_manage), db: Session = Depends(get_db),
):
    """Renames a relationship type and/or sets its `implies_equivalence`
    flag (§27's migration-carry-forward gate — see `models.py`'s own Phase
    11 notes). Every `ComplianceRequirementMapping.relationship_type_id`
    reference points at this row's id, never its name, so renaming has
    zero effect on existing mappings; toggling `implies_equivalence`
    likewise never touches any existing mapping row, only whether *future*
    migrations may offer carry-forward for a `replaced` pair linked by it."""
    relationship_type = db.get(ComplianceMappingRelationshipTypeDefinition, relationship_type_id)
    if relationship_type is None or relationship_type.organization_id != organization_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Relationship type not found.")
    existing = db.scalar(
        select(ComplianceMappingRelationshipTypeDefinition.id).where(
            ComplianceMappingRelationshipTypeDefinition.organization_id == organization_id,
            ComplianceMappingRelationshipTypeDefinition.name == payload.name,
            ComplianceMappingRelationshipTypeDefinition.id != relationship_type_id,
        )
    )
    if existing is not None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A relationship type with this name already exists.")
    relationship_type.name = payload.name
    relationship_type.implies_equivalence = payload.implies_equivalence
    log_event(db, entity_type="compliance_mapping_relationship_type", entity_id=relationship_type.id, action="renamed",
              actor_id=current_user.id, organization_id=organization_id,
              detail={"implies_equivalence": relationship_type.implies_equivalence})
    db.commit()
    db.refresh(relationship_type)
    return relationship_type


@router.delete("/mapping-relationship-types/{relationship_type_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_mapping_relationship_type(
    organization_id: UUID, relationship_type_id: UUID, reassign_to_id: UUID | None = Query(None),
    current_user: User = Depends(_require_manage), db: Session = Depends(get_db),
):
    """Deletes an organisation-scoped relationship type, applying the same
    shared rename/delete/reassign rules `delete_action_type` uses — no
    "must always retain at least one" floor (`allow_empty=True`), same
    reasoning as that endpoint's own docstring. Requires an explicit
    `reassign_to_id` to delete a type currently in use by any
    `ComplianceRequirementMapping` (409 naming the count if omitted)."""
    delete_definition_with_reassignment(
        db, definition_model=ComplianceMappingRelationshipTypeDefinition,
        scope_column=ComplianceMappingRelationshipTypeDefinition.organization_id, scope_id=organization_id,
        item_id=relationship_type_id, reassign_to_id=reassign_to_id,
        referencing_model=ComplianceRequirementMapping,
        referencing_fk_column=ComplianceRequirementMapping.relationship_type_id,
        referencing_fk_name="relationship_type_id", entity_type="compliance_mapping_relationship_type",
        noun="relationship type", plural_noun="requirement mapping(s)", reassign_verb="move",
        min_count_message="",  # unreachable: allow_empty=True skips the floor check that would use this
        actor_id=current_user.id, organization_id=organization_id, project_id=None,
        allow_empty=True,
    )
    db.commit()
