"""
Module: modules.decisions.project_router.relationships

Relationship endpoints (Phase 3 service functions): list a Decision's
relationships, and create a supersession, a Decision<->Requirement link,
or a Decision<->Decision link. See the package's own `__init__.py`
docstring for the full router-split account.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.enums import ArtefactType
from app.models.project import Project
from app.models.requirement import Requirement
from app.models.requirement_link_type import RequirementLinkTypeDefinition
from app.models.user import User
from app.modules.decisions.models import Decision
from app.modules.decisions.project_router._shared import _get_decision_in_project, _require_edit_role, _require_view
from app.modules.decisions.project_router.workflow import _apply_value_error_as_conflict
from app.modules.decisions.schemas import (
    DecisionDecisionLinkCreate,
    DecisionLinkOut,
    DecisionRequirementLinkCreate,
    DecisionSupersessionCreate,
)
from app.modules.decisions.service import (
    DECISION_ARTEFACT_TYPE,
    create_decision_decision_link,
    create_decision_requirement_link,
    create_supersession,
)
from app.services.relationships import get_all_links
from app.services.requirements import get_current_version

router = APIRouter(tags=["decisions-relationships"])


def _resolve_other_artefact_display(db: Session, other_type: str, other_id: UUID) -> tuple[str | None, str | None]:
    """Best-effort resolution of an artefact's own display code/name for
    `DecisionLinkOut` — see that schema's own docstring."""
    if other_type == DECISION_ARTEFACT_TYPE:
        other_decision = db.get(Decision, other_id)
        if other_decision is not None:
            return other_decision.unique_code, other_decision.title
    elif other_type == ArtefactType.REQUIREMENT.value:
        other_requirement = db.get(Requirement, other_id)
        if other_requirement is not None:
            version = get_current_version(db, other_requirement.id)
            return other_requirement.unique_code, version.name
    return None, None


def _link_to_out(db: Session, link, decision_id: UUID) -> DecisionLinkOut:
    is_outgoing = link.source_type == DECISION_ARTEFACT_TYPE and link.source_id == decision_id
    other_type = link.target_type if is_outgoing else link.source_type
    other_id = link.target_id if is_outgoing else link.source_id
    link_type = db.get(RequirementLinkTypeDefinition, link.link_type_id) if link.link_type_id else None
    if link_type is not None:
        display_name = link_type.forward_name if is_outgoing else link_type.reverse_name
    else:
        display_name = ""
    other_code, other_name = _resolve_other_artefact_display(db, other_type, other_id)
    return DecisionLinkOut(
        id=link.id, source_type=link.source_type, source_id=link.source_id,
        target_type=link.target_type, target_id=link.target_id, link_type_id=link.link_type_id,
        direction="outgoing" if is_outgoing else "incoming", display_name=display_name,
        other_type=other_type, other_id=other_id,
        other_display_code=other_code, other_display_name=other_name,
        created_by=link.created_by, created_at=link.created_at,
    )


@router.get("/{decision_id}/relationships", response_model=list[DecisionLinkOut])
def list_decision_relationships(
    project_id: UUID, decision_id: UUID,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Lists every relationship touching this Decision, in either
    direction — `services.relationships.get_all_links`, the generic
    equivalent of `routers.requirements.list_links`."""
    decision = _get_decision_in_project(db, project_id, decision_id)
    links = get_all_links(db, DECISION_ARTEFACT_TYPE, decision.id)
    return [_link_to_out(db, link, decision.id) for link in links]


@router.post("/{decision_id}/supersessions", response_model=DecisionLinkOut, status_code=status.HTTP_201_CREATED)
def create_decision_supersession(
    project_id: UUID, decision_id: UUID, payload: DecisionSupersessionCreate,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """`decision_id` (the new Decision) supersedes `payload.
    old_decision_id`. Gated on `decision_owner`, mirroring `routers.
    requirements.create_link`'s own precedent of requiring an edit-capable
    role to create a traceability relationship, not just view access."""
    project = db.get(Project, project_id)
    new_decision = _get_decision_in_project(db, project_id, decision_id)
    _require_edit_role(db, current_user, project)
    old_decision = _get_decision_in_project(db, project_id, payload.old_decision_id)
    link = _apply_value_error_as_conflict(
        create_supersession, db, new_decision=new_decision, old_decision=old_decision, actor_id=current_user.id,
    )
    db.commit()
    db.refresh(link)
    return _link_to_out(db, link, new_decision.id)


@router.post(
    "/{decision_id}/requirement-links", response_model=DecisionLinkOut, status_code=status.HTTP_201_CREATED,
)
def create_decision_requirement_link_endpoint(
    project_id: UUID, decision_id: UUID, payload: DecisionRequirementLinkCreate,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    project = db.get(Project, project_id)
    decision = _get_decision_in_project(db, project_id, decision_id)
    _require_edit_role(db, current_user, project)
    requirement = db.get(Requirement, payload.requirement_id)
    if requirement is None or requirement.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Requirement not found.")
    link = _apply_value_error_as_conflict(
        create_decision_requirement_link, db, decision=decision, requirement=requirement,
        kind=payload.kind, actor_id=current_user.id,
    )
    db.commit()
    db.refresh(link)
    return _link_to_out(db, link, decision.id)


@router.post(
    "/{decision_id}/decision-links", response_model=DecisionLinkOut, status_code=status.HTTP_201_CREATED,
)
def create_decision_decision_link_endpoint(
    project_id: UUID, decision_id: UUID, payload: DecisionDecisionLinkCreate,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    project = db.get(Project, project_id)
    source_decision = _get_decision_in_project(db, project_id, decision_id)
    _require_edit_role(db, current_user, project)
    target_decision = _get_decision_in_project(db, project_id, payload.target_decision_id)
    link = _apply_value_error_as_conflict(
        create_decision_decision_link, db, source_decision=source_decision, target_decision=target_decision,
        kind=payload.kind, actor_id=current_user.id,
    )
    db.commit()
    db.refresh(link)
    return _link_to_out(db, link, source_decision.id)
