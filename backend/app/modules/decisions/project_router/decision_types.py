"""
Module: modules.decisions.project_router.decision_types

Decision Types (project-scoped definition table): list/create/rename/
move/delete. See the package's own `__init__.py` docstring for the full
router-split account.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.project import Project
from app.models.user import User
from app.modules.decisions.models import Decision, DecisionTypeDefinition
from app.modules.decisions.project_router._shared import _require_view
from app.modules.decisions.schemas import DecisionTypeCreate, DecisionTypeOut, DecisionTypeUpdate
from app.modules.decisions.service import resolve_effective_decision_types
from app.schemas.project import MoveDirection
from app.services.audit import log_event
from app.services.definitions import delete_definition_with_reassignment
from app.services.ordering import move_ordered
from app.services.rbac import require_module_role

router = APIRouter(tags=["decisions-types"])

# Factory called once, at router-definition time — same convention as
# every other module router in this codebase (`modules.compliance.
# project_router`'s own comment on this).
_require_owner_role = require_module_role("decisions", "decision_owner")


def _get_decision_type_in_project(db: Session, project_id: UUID, decision_type_id: UUID) -> DecisionTypeDefinition:
    """Fetches a decision type this project literally owns (for
    rename/move/delete, which must never act on a row a hierarchical-
    project fallback merely makes *visible* to this project — see
    `core._validate_effective_decision_type` for the "may a Decision
    reference this type" question instead, which is deliberately broader)."""
    decision_type = db.get(DecisionTypeDefinition, decision_type_id)
    if decision_type is None or decision_type.project_id != project_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid decision_type_id.")
    return decision_type


@router.get("/decision-types", response_model=list[DecisionTypeOut])
def list_decision_types(
    project_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Lists a project's decision types — any project member may select one
    when creating a Decision, so listing isn't manage-only (only
    create/rename/move/delete are). A project with none of its own falls
    back to its nearest ancestor's (hierarchical projects, always on
    independent of RBAC inheritance settings — Phase 9, 2026-09-22 — see
    `service.resolve_effective_decision_types`)."""
    return resolve_effective_decision_types(db, project_id)


@router.post("/decision-types", response_model=DecisionTypeOut, status_code=status.HTTP_201_CREATED)
def create_decision_type(
    project_id: UUID, payload: DecisionTypeCreate,
    current_user: User = Depends(_require_owner_role), db: Session = Depends(get_db),
):
    existing = db.scalar(
        select(DecisionTypeDefinition.id).where(
            DecisionTypeDefinition.project_id == project_id, DecisionTypeDefinition.name == payload.name
        )
    )
    if existing is not None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A decision type with this name already exists.")
    count = len(
        db.scalars(select(DecisionTypeDefinition.id).where(DecisionTypeDefinition.project_id == project_id)).all()
    )
    decision_type = DecisionTypeDefinition(project_id=project_id, name=payload.name, sort_order=count)
    db.add(decision_type)
    db.flush()
    log_event(db, entity_type="decision_type_definition", entity_id=decision_type.id, action="created",
              actor_id=current_user.id, project_id=project_id, detail={"name": decision_type.name})
    db.commit()
    db.refresh(decision_type)
    return decision_type


@router.patch("/decision-types/{decision_type_id}", response_model=DecisionTypeOut)
def rename_decision_type(
    project_id: UUID, decision_type_id: UUID, payload: DecisionTypeUpdate,
    current_user: User = Depends(_require_owner_role), db: Session = Depends(get_db),
):
    decision_type = _get_decision_type_in_project(db, project_id, decision_type_id)
    existing = db.scalar(
        select(DecisionTypeDefinition.id).where(
            DecisionTypeDefinition.project_id == project_id, DecisionTypeDefinition.name == payload.name,
            DecisionTypeDefinition.id != decision_type_id,
        )
    )
    if existing is not None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A decision type with this name already exists.")
    decision_type.name = payload.name
    log_event(db, entity_type="decision_type_definition", entity_id=decision_type.id, action="renamed",
              actor_id=current_user.id, project_id=project_id)
    db.commit()
    db.refresh(decision_type)
    return decision_type


@router.post("/decision-types/{decision_type_id}/move", response_model=DecisionTypeOut)
def move_decision_type(
    project_id: UUID, decision_type_id: UUID, payload: MoveDirection,
    current_user: User = Depends(_require_owner_role), db: Session = Depends(get_db),
):
    result = move_ordered(
        db, DecisionTypeDefinition, [DecisionTypeDefinition.project_id == project_id], decision_type_id, payload.direction
    )
    log_event(db, entity_type="decision_type_definition", entity_id=decision_type_id, action="reordered",
              actor_id=current_user.id, project_id=project_id, detail={"direction": payload.direction})
    db.commit()
    return result


@router.delete("/decision-types/{decision_type_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_decision_type(
    project_id: UUID, decision_type_id: UUID, reassign_to_id: UUID | None = Query(None),
    current_user: User = Depends(_require_owner_role), db: Session = Depends(get_db),
):
    """Deletes a project's Decision Type, applying the shared rename/
    delete/reassign rules (`services.definitions`). Unlike `Decision
    Template` (org-scoped, no persistent FK from `Decision` — see Phase 0
    addendum item 6), `Decision.decision_type_id` **is** a real, non-null
    FK, so deleting an in-use type requires an explicit `reassign_to_id`
    (409 naming the count if omitted) — resolved independently of the
    template answer, per this phase's own build instructions, rather than
    copying it.

    `allow_empty=project.parent_project_id is not None` (Phase 9,
    2026-09-22, **Decided by: User** — supersedes this endpoint's own
    earlier Phase 4 **Decided by: Agent** call that Decision Types would
    never allow emptying a project, unlike `ActionTypeDefinition`): a
    project with a parent may now be emptied of its own decision types,
    since it falls back to its nearest ancestor's
    (`service.resolve_effective_decision_types`) — exact mirror of
    `routers.action_types.delete_action_type`'s identical guard. A *root*
    project (no parent) still can't be emptied — `min_count_message` below
    still fires for it."""
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found.")
    delete_definition_with_reassignment(
        db, definition_model=DecisionTypeDefinition, scope_column=DecisionTypeDefinition.project_id,
        scope_id=project_id, item_id=decision_type_id, reassign_to_id=reassign_to_id,
        referencing_model=Decision, referencing_fk_column=Decision.decision_type_id,
        referencing_fk_name="decision_type_id", entity_type="decision_type_definition", noun="decision type",
        plural_noun="decision(s)", reassign_verb="move",
        min_count_message="A project must always have at least one decision type.",
        allow_empty=project.parent_project_id is not None,
        actor_id=current_user.id, organization_id=project.organization_id, project_id=project_id,
    )
    db.commit()
