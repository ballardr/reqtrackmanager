"""
Module: modules.compliance.router.version_required_actions

Required actions nested under a standard version's requirement
(Phase 6): create/list/get/update/delete/reorder, all `DRAFT`-version-
only (`_require_draft_version`) — sibling bucket to
`version_requirements.py`, split out separately since that bucket was
still large on its own. `_get_required_action_or_404` is local to this
file only (verified by call-site grep before this split).
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.modules.compliance.models import (
    ComplianceActionTypeDefinition,
    ComplianceRequiredAction,
    ComplianceRequirement,
    ComplianceStandard,
    ComplianceStandardVersion,
)
from app.modules.compliance.router._shared import (
    _get_requirement_or_404,
    _require_draft_version,
    _require_standard_manage_or_contribute,
    _require_view,
)
from app.modules.compliance.schemas import ComplianceRequiredActionCreate, ComplianceRequiredActionOut, ComplianceRequiredActionUpdate
from app.schemas.project import MoveDirection
from app.services.audit import log_event
from app.services.ordering import move_ordered

router = APIRouter(tags=["compliance-org-version-required-actions"])


def _get_required_action_or_404(
    db: Session,
    organization_id: UUID,
    standard_id: UUID,
    version_id: UUID,
    requirement_id: UUID,
    action_id: UUID,
) -> tuple[ComplianceStandard, ComplianceStandardVersion, ComplianceRequirement, ComplianceRequiredAction]:
    standard, version, requirement = _get_requirement_or_404(
        db, organization_id, standard_id, version_id, requirement_id
    )
    action = db.get(ComplianceRequiredAction, action_id)
    if action is None or action.requirement_id != requirement.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Compliance required action not found.")
    return standard, version, requirement, action


@router.post(
    "/standards/{standard_id}/versions/{version_id}/requirements/{requirement_id}/required-actions",
    response_model=ComplianceRequiredActionOut, status_code=status.HTTP_201_CREATED,
)
def create_required_action(
    organization_id: UUID, standard_id: UUID, version_id: UUID, requirement_id: UUID,
    payload: ComplianceRequiredActionCreate,
    current_user: User = Depends(_require_standard_manage_or_contribute), db: Session = Depends(get_db),
):
    """Creates a required action under a requirement (§6). 409 if the
    owning version is no longer a draft. `action_type_id` must be an
    organisation-scoped `ComplianceActionTypeDefinition` belonging to this
    same organisation."""
    _, version, requirement = _get_requirement_or_404(db, organization_id, standard_id, version_id, requirement_id)
    _require_draft_version(version)

    action_type = db.get(ComplianceActionTypeDefinition, payload.action_type_id)
    if action_type is None or action_type.organization_id != organization_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "action_type_id must be an action type in this organisation.")

    count = len(
        db.scalars(
            select(ComplianceRequiredAction.id).where(ComplianceRequiredAction.requirement_id == requirement.id)
        ).all()
    )
    action = ComplianceRequiredAction(
        requirement_id=requirement.id,
        action_type_id=payload.action_type_id,
        name=payload.name,
        description=payload.description,
        is_mandatory=payload.is_mandatory,
        sort_order=count,
        created_by=current_user.id,
    )
    db.add(action)
    db.flush()
    log_event(db, entity_type="compliance_required_action", entity_id=action.id, action="created",
              actor_id=current_user.id, organization_id=organization_id, detail={"name": action.name})
    db.commit()
    db.refresh(action)
    return action


@router.get(
    "/standards/{standard_id}/versions/{version_id}/requirements/{requirement_id}/required-actions",
    response_model=list[ComplianceRequiredActionOut],
)
def list_required_actions(
    organization_id: UUID, standard_id: UUID, version_id: UUID, requirement_id: UUID,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Lists a requirement's required actions, ordered by `sort_order`."""
    _, _, requirement = _get_requirement_or_404(db, organization_id, standard_id, version_id, requirement_id)
    return db.scalars(
        select(ComplianceRequiredAction)
        .where(ComplianceRequiredAction.requirement_id == requirement.id)
        .order_by(ComplianceRequiredAction.sort_order)
    ).all()


@router.get(
    "/standards/{standard_id}/versions/{version_id}/requirements/{requirement_id}/required-actions/{action_id}",
    response_model=ComplianceRequiredActionOut,
)
def get_required_action(
    organization_id: UUID, standard_id: UUID, version_id: UUID, requirement_id: UUID, action_id: UUID,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Fetches a single required action."""
    _, _, _, action = _get_required_action_or_404(
        db, organization_id, standard_id, version_id, requirement_id, action_id
    )
    return action


@router.patch(
    "/standards/{standard_id}/versions/{version_id}/requirements/{requirement_id}/required-actions/{action_id}",
    response_model=ComplianceRequiredActionOut,
)
def update_required_action(
    organization_id: UUID, standard_id: UUID, version_id: UUID, requirement_id: UUID, action_id: UUID,
    payload: ComplianceRequiredActionUpdate,
    current_user: User = Depends(_require_standard_manage_or_contribute), db: Session = Depends(get_db),
):
    """Updates a required action's action type/name/description/
    is_mandatory. 409 if the owning version is no longer a draft."""
    _, version, _, action = _get_required_action_or_404(
        db, organization_id, standard_id, version_id, requirement_id, action_id
    )
    _require_draft_version(version)

    action_type = db.get(ComplianceActionTypeDefinition, payload.action_type_id)
    if action_type is None or action_type.organization_id != organization_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "action_type_id must be an action type in this organisation.")

    action.action_type_id = payload.action_type_id
    action.name = payload.name
    action.description = payload.description
    action.is_mandatory = payload.is_mandatory
    log_event(db, entity_type="compliance_required_action", entity_id=action.id, action="updated",
              actor_id=current_user.id, organization_id=organization_id, detail={"name": action.name})
    db.commit()
    db.refresh(action)
    return action


@router.delete(
    "/standards/{standard_id}/versions/{version_id}/requirements/{requirement_id}/required-actions/{action_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_required_action(
    organization_id: UUID, standard_id: UUID, version_id: UUID, requirement_id: UUID, action_id: UUID,
    current_user: User = Depends(_require_standard_manage_or_contribute), db: Session = Depends(get_db),
):
    """Deletes a required action. 409 if the owning version is no longer a
    draft. No manual cascade needed for its `action_type_id` FK (implicit
    RESTRICT, not CASCADE, per Phase 5's schema) — deleting the required
    action itself is unaffected by that."""
    _, version, _, action = _get_required_action_or_404(
        db, organization_id, standard_id, version_id, requirement_id, action_id
    )
    _require_draft_version(version)
    log_event(db, entity_type="compliance_required_action", entity_id=action.id, action="deleted",
              actor_id=current_user.id, organization_id=organization_id, detail={"name": action.name})
    db.delete(action)
    db.commit()


@router.post(
    "/standards/{standard_id}/versions/{version_id}/requirements/{requirement_id}/required-actions/{action_id}/move",
    response_model=ComplianceRequiredActionOut,
)
def move_required_action(
    organization_id: UUID, standard_id: UUID, version_id: UUID, requirement_id: UUID, action_id: UUID,
    payload: MoveDirection,
    current_user: User = Depends(_require_standard_manage_or_contribute), db: Session = Depends(get_db),
):
    """Moves a required action up/down among its siblings (same
    `requirement_id`). 409 if the owning version is no longer a draft."""
    _, version, _, action = _get_required_action_or_404(
        db, organization_id, standard_id, version_id, requirement_id, action_id
    )
    _require_draft_version(version)
    result = move_ordered(
        db, ComplianceRequiredAction, [ComplianceRequiredAction.requirement_id == requirement_id],
        action_id, payload.direction,
    )
    log_event(db, entity_type="compliance_required_action", entity_id=action_id, action="reordered",
              actor_id=current_user.id, organization_id=organization_id, detail={"direction": payload.direction})
    db.commit()
    return result
