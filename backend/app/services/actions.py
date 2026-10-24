"""
Module: services.actions

Core business logic for requirement actions: unique identifier generation,
mirroring `services.requirements`'s `generate_unique_code`/sequence-counter
pattern exactly (same per-project monotonic counter idea, `Project.
next_action_seq` instead of `next_requirement_seq`), the outcome-transition
stamping rule (`completed_at`/`completed_by` set the moment
`outcome_status` first moves away from PENDING), and the
`get_requirement_action_in_project` IDOR-guard helper (mirrors
`routers.requirements._get_requirement_in_project`) and `action_to_out`,
the API-response builder. All three live here rather than as router-private
functions because they're needed by two routers — `routers.actions` (the
action's own CRUD) and `routers.requirements` (the requirement<->action
linking endpoints) — and this codebase has no precedent for one router
importing a private helper from another.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, object_session

from app.models.enums import RequirementActionOutcome, ReviewTargetType
from app.models.project import Project
from app.models.requirement_action import RequirementAction
from app.models.user import User
from app.schemas.action import RequirementActionOut
from app.schemas.principal import PrincipalOut, PrincipalRef
from app.services import engagement
from app.services.audit import log_event
from app.services.principals import principal_columns, principal_labels, principal_ref, validate_principal
from app.services.project_hierarchy import resolve_effective_action_types
from app.services.rbac import lock_project_for_update


def _next_sequence(project: Project) -> int:
    """Returns the next action sequence number for `project`, advancing the
    counter so it is never reused (mirrors `services.requirements.
    _next_sequence`), including for archived actions.

    Locks the project row and re-reads the counter first, for the same
    concurrent-create race (2026-10-05)."""
    db = object_session(project)
    lock_project_for_update(db, project.id)
    db.refresh(project, attribute_names=["next_action_seq"])
    seq = project.next_action_seq
    project.next_action_seq = seq + 1
    return seq


def generate_unique_code(project: Project) -> str:
    """Builds a unique, never-reused action identifier, e.g. "ACT-003"."""
    seq = _next_sequence(project)
    return f"ACT-{seq:03d}"


def apply_outcome_transition(action: RequirementAction, new_outcome: RequirementActionOutcome, actor: User) -> None:
    """Applies an outcome status change to `action`, stamping
    `completed_at`/`completed_by` the moment the outcome first moves away
    from PENDING (to COMPLETED or FAILED) — capturing "when was this
    action's outcome actually recorded" regardless of which of the two
    terminal outcomes it landed on. Moving back to PENDING (a correction)
    clears both stamps again, mirroring `uncomplete_requirement`'s "revert a
    mistake" pattern.

    Args:
        action: The action being updated (mutated in place; not committed).
        new_outcome: The outcome status to transition to.
        actor: The user performing the transition (recorded as
            `completed_by` when leaving PENDING).
    """
    action.outcome_status = new_outcome
    if new_outcome == RequirementActionOutcome.PENDING:
        action.completed_at = None
        action.completed_by = None
    else:
        action.completed_at = datetime.now(UTC)
        action.completed_by = actor.id


def get_requirement_action_in_project(db: Session, project_id: UUID, action_id: UUID) -> RequirementAction:
    """Loads a requirement action and 404s unless it belongs to `project_id`.

    Without this check, an endpoint that only verifies the caller's role on
    `project_id` would let any project member read or write an action
    belonging to a different, inaccessible project by supplying its id — an
    IDOR (mirrors `routers.requirements._get_requirement_in_project`, see
    its docstring for the full reasoning). Every handler taking both a
    `project_id` and an `action_id` must load through this helper rather
    than trusting `action_id` alone.

    Raises:
        HTTPException: 404 if `action_id` isn't found in `project_id`.
    """
    action = db.get(RequirementAction, action_id)
    if action is None or action.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Requirement action not found.")
    return action


def assignee_labels(db: Session, actions: Sequence[RequirementAction]) -> dict[tuple[str, UUID], PrincipalOut]:
    """Display data for the assignee of every action in `actions`, in one batch."""
    return principal_labels(db, [principal_ref(a.assignee_type, a.assignee_id) for a in actions])


def action_to_out(
    db: Session, action: RequirementAction, comment_count: int | None = None,
    labels: dict[tuple[str, UUID], PrincipalOut] | None = None,
) -> RequirementActionOut:
    """Builds the API response shape for an action, including its
    discussion thread's comment count (not a column on `RequirementAction`
    itself, so it can't just fall out of `from_attributes`).

    Args:
        db: Database session.
        action: The action.
        comment_count: Precomputed by list callers (`engagement.
            get_comment_counts`); queried when omitted.
        labels: Pre-resolved assignee labels (`assignee_labels`) when building many; resolved here when omitted.
    """
    labels = labels if labels is not None else assignee_labels(db, [action])
    return RequirementActionOut(
        id=action.id, project_id=action.project_id, unique_code=action.unique_code,
        action_type_id=action.action_type_id, title=action.title, description=action.description,
        outcome_status=action.outcome_status, due_date=action.due_date,
        assignee=labels[(action.assignee_type, action.assignee_id)] if action.assignee_id else None,
        completed_at=action.completed_at, completed_by=action.completed_by, creator_id=action.creator_id,
        is_archived=action.is_archived, archived_at=action.archived_at, archived_by=action.archived_by,
        created_at=action.created_at, updated_at=action.updated_at,
        comment_count=(
            comment_count if comment_count is not None
            else engagement.get_comment_count(db, ReviewTargetType.ACTION, action.id)
        ),
    )


UNSET: Any = object()
"""Marks a nullable argument of `edit_action` as "leave unchanged", since `None` there means "clear"."""


def validate_action_type(db: Session, project_id: UUID, action_type_id: UUID) -> None:
    """400s unless `action_type_id` is one of `project_id`'s *effective* action types: its own, or
    (hierarchical projects, always on) a fallback inherited from its nearest ancestor
    (`services.project_hierarchy.resolve_effective_action_types`). This is what lets a `RequirementAction`
    in a child project reference the parent's `ActionTypeDefinition` row directly.

    Raises:
        HTTPException: 400 when the type is not available to the project.
    """
    if action_type_id not in {at.id for at in resolve_effective_action_types(db, project_id)}:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "action_type_id must be an action type defined in this project, or inherited from a parent project.",
        )


def create_action(
    db: Session, project: Project, actor: User, *, title: str, description: str = "", action_type_id: UUID,
    assignee: PrincipalRef | None = None, due_date: date | None = None,
) -> RequirementAction:
    """Creates a standalone action and writes its `created` audit event (the caller commits).

    Raises:
        HTTPException: 400 for an action type or assignee that is not valid for the project.
    """
    validate_action_type(db, project.id, action_type_id)
    validate_principal(db, assignee, organization_id=project.organization_id, project_id=project.id, field="assignee")
    action = RequirementAction(
        project_id=project.id, unique_code=generate_unique_code(project), action_type_id=action_type_id,
        title=title, description=description, **principal_columns("assignee", assignee),
        due_date=due_date, creator_id=actor.id,
    )
    db.add(action)
    db.flush()
    log_event(db, entity_type="requirement_action", entity_id=action.id, action="created",
              actor_id=actor.id, project_id=project.id, organization_id=project.organization_id,
              detail={"unique_code": action.unique_code, "title": action.title})
    return action


def edit_action(
    db: Session, project: Project, actor: User, action: RequirementAction, *, title: str | None = None,
    description: str | None = None, action_type_id: UUID | None = None, assignee: Any = UNSET, due_date: Any = UNSET,
    outcome_status: RequirementActionOutcome | None = None,
) -> RequirementAction:
    """Edits an action and writes its `updated` audit event (the caller commits). `None` leaves a field as it
    is; `assignee` and `due_date` use `UNSET` for that, so `None` clears them. A changed outcome stamps
    `completed_at`/`completed_by` (`apply_outcome_transition`).

    Raises:
        HTTPException: 400 for an action type or assignee that is not valid for the project.
    """
    if action_type_id is not None:
        validate_action_type(db, project.id, action_type_id)
        action.action_type_id = action_type_id
    if assignee is not UNSET:
        validate_principal(db, assignee, organization_id=project.organization_id, project_id=project.id, field="assignee")
        for column, value in principal_columns("assignee", assignee).items():
            setattr(action, column, value)
    if title is not None:
        action.title = title
    if description is not None:
        action.description = description
    if due_date is not UNSET:
        action.due_date = due_date
    if outcome_status is not None and outcome_status != action.outcome_status:
        apply_outcome_transition(action, outcome_status, actor)
    log_event(db, entity_type="requirement_action", entity_id=action.id, action="updated",
              actor_id=actor.id, project_id=project.id, organization_id=project.organization_id,
              detail={"outcome_status": action.outcome_status.value})
    return action


def list_actions_filtered(
    db: Session, project_id: UUID, *, outcome_status: RequirementActionOutcome | None = None,
    action_type_id: UUID | None = None, include_archived: bool = False,
) -> list[RequirementAction]:
    """One project's actions by code, narrowed by the list endpoint's filters: the single implementation
    behind that endpoint and the record table export, so a filter added here reaches both.

    Args:
        db: Active session (read only).
        project_id: The project.
        outcome_status: Only actions with this outcome.
        action_type_id: Only actions of this type.
        include_archived: Include archived actions.
    """
    query = select(RequirementAction).where(RequirementAction.project_id == project_id)
    if not include_archived:
        query = query.where(RequirementAction.is_archived.is_(False))
    if outcome_status is not None:
        query = query.where(RequirementAction.outcome_status == outcome_status)
    if action_type_id is not None:
        query = query.where(RequirementAction.action_type_id == action_type_id)
    return list(db.scalars(query.order_by(RequirementAction.unique_code)).all())
