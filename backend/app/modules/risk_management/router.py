"""
Module: modules.risk_management.router

Organisation-scoped API for the Risk Management module, mounted at
`/api/v1/orgs/{organization_id}/modules/risk_management`: the org Risk type
vocabulary (list, create, reorder, rename/deactivate, delete). Risks themselves
are project-scoped (`project_router.py`).

RBAC: sub-component enablement to view the list; every change needs
`_shared.require_risk_type_admin` (the `risk_type_admin` module role, composing
with org admin). Scoring levels, bands and cell ratings for the `risk` scheme are
configured through core's generic scoring endpoints, gated by the same role.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.modules.risk_management import _shared as sh
from app.modules.risk_management.models import RiskTypeDefinition
from app.modules.risk_management.service import RISK_MODULE_KEY, RISK_SUBCOMPONENT_KEY, RISK_TYPES
from app.schemas.project import MoveDirection
from app.schemas.type_vocabulary import OrgTypeCreate, OrgTypeOut, OrgTypeUpdate
from app.services.audit import log_event
from app.services.ordering import move_ordered
from app.services.rbac import require_org_subcomponent_enabled

router = APIRouter(prefix=f"/api/v1/orgs/{{organization_id}}/modules/{RISK_MODULE_KEY}", tags=["risk-management-org"])

_require_view = require_org_subcomponent_enabled(RISK_MODULE_KEY, RISK_SUBCOMPONENT_KEY)


@router.get("/risk-types", response_model=list[OrgTypeOut])
def list_risk_types(organization_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db)):
    """Lists the organisation's Risk types, including inactive ones (an admin
    needs to see and re-activate them)."""
    return db.scalars(
        select(RiskTypeDefinition).where(RiskTypeDefinition.organization_id == organization_id)
        .order_by(RiskTypeDefinition.sort_order)
    ).all()


@router.post("/risk-types", response_model=OrgTypeOut, status_code=status.HTTP_201_CREATED)
def create_risk_type(
    organization_id: UUID, payload: OrgTypeCreate, current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Creates an org Risk type at the end of the order. Needs `risk_type_admin`; 400 on a duplicate name."""
    sh.require_risk_type_admin(db, current_user, organization_id=organization_id)
    try:
        row = RISK_TYPES.create_org_type(db, organization_id, payload.name)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    log_event(db, entity_type="risk_type_definition", entity_id=row.id, action="created", actor_id=current_user.id,
              organization_id=organization_id, detail={"name": row.name})
    db.commit()
    db.refresh(row)
    return row


@router.post("/risk-types/{type_id}/move", response_model=OrgTypeOut)
def move_risk_type(
    organization_id: UUID, type_id: UUID, payload: MoveDirection,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Moves a type up or down one place. Needs `risk_type_admin`."""
    sh.require_risk_type_admin(db, current_user, organization_id=organization_id)
    sh.get_org_type(db, organization_id, type_id)
    result = move_ordered(
        db, RiskTypeDefinition, [RiskTypeDefinition.organization_id == organization_id], type_id, payload.direction,
    )
    log_event(db, entity_type="risk_type_definition", entity_id=type_id, action="reordered", actor_id=current_user.id,
              organization_id=organization_id, detail={"direction": payload.direction})
    db.commit()
    return result


@router.patch("/risk-types/{type_id}", response_model=OrgTypeOut)
def update_risk_type(
    organization_id: UUID, type_id: UUID, payload: OrgTypeUpdate,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Renames and/or activates/deactivates a type. References are by id, so
    renaming never affects existing risks."""
    sh.require_risk_type_admin(db, current_user, organization_id=organization_id)
    row = sh.get_org_type(db, organization_id, type_id)
    if payload.name is not None:
        clash = db.scalar(select(RiskTypeDefinition.id).where(
            RiskTypeDefinition.organization_id == organization_id, RiskTypeDefinition.name == payload.name,
            RiskTypeDefinition.id != type_id,
        ))
        if clash is not None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "A Risk type with this name already exists.")
        row.name = payload.name
    if payload.is_active is not None:
        row.is_active = payload.is_active
    log_event(db, entity_type="risk_type_definition", entity_id=row.id, action="updated", actor_id=current_user.id,
              organization_id=organization_id)
    db.commit()
    db.refresh(row)
    return row


@router.delete("/risk-types/{type_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_risk_type(
    organization_id: UUID, type_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Deletes a type; 409 while any project still references it."""
    sh.require_risk_type_admin(db, current_user, organization_id=organization_id)
    row = sh.get_org_type(db, organization_id, type_id)
    sh.apply_value_error_as_conflict(RISK_TYPES.delete_org_type, db, row)
    log_event(db, entity_type="risk_type_definition", entity_id=type_id, action="deleted", actor_id=current_user.id,
              organization_id=organization_id)
    db.commit()
