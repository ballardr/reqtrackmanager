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

from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.enums import RequirementActionOutcome, ReviewTargetType
from app.models.project import Project
from app.models.requirement_action import RequirementAction
from app.models.user import User
from app.schemas.action import RequirementActionOut
from app.services import engagement


def _next_sequence(project: Project) -> int:
    """Returns the next action sequence number for `project`, advancing the
    counter so it is never reused (mirrors `services.requirements.
    _next_sequence`), including for archived actions."""
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


def action_to_out(db: Session, action: RequirementAction) -> RequirementActionOut:
    """Builds the API response shape for an action, including its
    discussion thread's comment count (not a column on `RequirementAction`
    itself, so it can't just fall out of `from_attributes`)."""
    return RequirementActionOut(
        id=action.id, project_id=action.project_id, unique_code=action.unique_code,
        action_type_id=action.action_type_id, title=action.title, description=action.description,
        outcome_status=action.outcome_status, assignee_id=action.assignee_id, due_date=action.due_date,
        completed_at=action.completed_at, completed_by=action.completed_by, creator_id=action.creator_id,
        is_archived=action.is_archived, archived_at=action.archived_at, archived_by=action.archived_by,
        created_at=action.created_at, updated_at=action.updated_at,
        comment_count=engagement.get_comment_count(db, ReviewTargetType.ACTION, action.id),
    )
