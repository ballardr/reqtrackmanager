"""
Module: modules.decisions.project_router.workflow

Lifecycle transitions (Phase 2 service functions): propose/submit-for-
review/approve/reject. `approve`/`reject` carry the AI-approval MCP gate
(`require_ai_approvals_enabled`) added 2026-09-22 — see
`approve_decision_endpoint`'s own docstring below. Also home for
`_apply_value_error_as_conflict` (imported by `relationships.py`, the
only other bucket that calls into a Phase 2/3 `service.py` function).
See the package's own `__init__.py` docstring for the full router-split
account.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_request_channel
from app.models.project import Project
from app.models.user import User
from app.modules.decisions.models import Decision
from app.modules.decisions.project_router._shared import _get_decision_in_project, _require_edit_role, _require_view
from app.modules.decisions.project_router.core import _decision_to_out
from app.modules.decisions.schemas import DecisionOut, DecisionTransitionRequest
from app.modules.decisions.service import approve_decision, propose_decision, reject_decision, submit_decision_for_review
from app.services.rbac import require_ai_approvals_enabled, require_module_role

router = APIRouter(tags=["decisions-workflow"])

# Factory called once, at router-definition time — same convention as
# every other module router in this codebase (`modules.compliance.
# project_router`'s own comment on this).
_require_approver = require_module_role("decisions", "decision_approver")


def _require_owner_of_decision_or_role(db: Session, current_user: User, project: Project, decision: Decision) -> None:
    """Gate for `propose`/`submit-for-review` — see this package's own
    `__init__.py` docstring for why this is a distinct, looser gate than
    `_require_edit_role`."""
    if current_user.id == decision.owner_id:
        return
    _require_edit_role(db, current_user, project)


def _get_decision_in_project_for_update(db: Session, project_id: UUID, decision_id: UUID) -> Decision:
    """Row-locked variant of `_get_decision_in_project`, for `approve`/
    `reject` only (2026-09-23 hardening pass) — mirrors `change_requests.
    workflow.decide_change_request`'s own `with_for_update()` fix for the
    identical race: two concurrent decide-type calls on the same row (e.g.
    one approve, one reject) would otherwise both read the pre-transition
    status before either commits, both pass `_ALLOWED_TRANSITIONS`
    validation in `service.py`, and both apply their side effects —
    whichever commits last silently overwrites the other's decision, and
    `_supersede_predecessors`' side effect on `approve` could fire off a
    status a losing concurrent write already invalidated. The lock
    serializes the two calls so the second one's status check runs against
    the first one's already-committed result. Not used by `propose`/
    `submit-for-review`/read endpoints — those don't race a same-row
    decide-type transition the way approve/reject do."""
    decision = db.scalar(select(Decision).where(Decision.id == decision_id).with_for_update())
    if decision is None or decision.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Decision not found.")
    return decision


def _apply_value_error_as_conflict(fn, *args, **kwargs):
    """Calls a Phase 2/3 `service.py` function, translating its `ValueError`
    (that layer's own "validation failed" convention) into an HTTP 409 —
    the translation every one of `service.py`'s own docstrings names as
    "Phase 4's router" responsibility."""
    try:
        return fn(*args, **kwargs)
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc


@router.post("/{decision_id}/propose", response_model=DecisionOut)
def propose_decision_endpoint(
    project_id: UUID, decision_id: UUID,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    project = db.get(Project, project_id)
    decision = _get_decision_in_project(db, project_id, decision_id)
    _require_owner_of_decision_or_role(db, current_user, project, decision)
    _apply_value_error_as_conflict(propose_decision, db, decision, current_user.id)
    db.commit()
    db.refresh(decision)
    return _decision_to_out(decision)


@router.post("/{decision_id}/submit-for-review", response_model=DecisionOut)
def submit_decision_for_review_endpoint(
    project_id: UUID, decision_id: UUID,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    project = db.get(Project, project_id)
    decision = _get_decision_in_project(db, project_id, decision_id)
    _require_owner_of_decision_or_role(db, current_user, project, decision)
    _apply_value_error_as_conflict(submit_decision_for_review, db, decision, current_user.id)
    db.commit()
    db.refresh(decision)
    return _decision_to_out(decision)


@router.post("/{decision_id}/approve", response_model=DecisionOut)
def approve_decision_endpoint(
    project_id: UUID, decision_id: UUID, payload: DecisionTransitionRequest,
    current_user: User = Depends(_require_approver), db: Session = Depends(get_db),
    channel: str = Depends(get_request_channel),
):
    """Formally approves a Decision (`UNDER_REVIEW` -> `APPROVED`) — gated
    the same as every other mutating endpoint this router names as
    approval-type (the flat `decision_approver` module role).

    No longer marked `APPROVAL_ACTION_ROUTE_EXTRA` (2026-09-22, see
    docs/decisions.md's "Decision Management MCP approval gate" entry,
    following up on the compliance module's identical "Compliance MCP
    write tools + generalized AI approval gate" entry): this is now MCP-
    reachable exactly like core's `requirements.approve_requirement`/
    `complete_requirement`, `change_requests.decide_change_request`, and
    `modules.compliance.project_router.approve_requirement` — when reached
    through the MCP server (`channel == "mcp"`), additionally requires
    this project and its organisation to both have explicitly enabled AI
    approval (`require_ai_approvals_enabled`); a plain UI/API call is
    unaffected by that flag either way."""
    project = db.get(Project, project_id)
    if channel == "mcp":
        require_ai_approvals_enabled(db, project)
    decision = _get_decision_in_project_for_update(db, project_id, decision_id)
    _apply_value_error_as_conflict(
        approve_decision, db, decision, current_user.id, comment=payload.comment, via_mcp=channel == "mcp",
    )
    db.commit()
    db.refresh(decision)
    return _decision_to_out(decision)


@router.post("/{decision_id}/reject", response_model=DecisionOut)
def reject_decision_endpoint(
    project_id: UUID, decision_id: UUID, payload: DecisionTransitionRequest,
    current_user: User = Depends(_require_approver), db: Session = Depends(get_db),
    channel: str = Depends(get_request_channel),
):
    """Formally rejects a Decision (`PROPOSED`/`UNDER_REVIEW` -> `REJECTED`).
    Rejection requires a comment — mirrors `record_review_outcome`'s
    mandatory-comment-on-`FAILED` rule (`routers.requirements.py`) and
    `reject_requirement`'s mandatory `decision_note`
    (`modules.compliance.project_router`): a rejection must never appear
    with no indication of why.

    No longer marked `APPROVAL_ACTION_ROUTE_EXTRA` (2026-09-22) — see
    `approve_decision_endpoint`'s docstring above; gated the same way when
    reached through the MCP server."""
    if not (payload.comment or "").strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A comment is required to reject a Decision.")
    project = db.get(Project, project_id)
    if channel == "mcp":
        require_ai_approvals_enabled(db, project)
    decision = _get_decision_in_project_for_update(db, project_id, decision_id)
    _apply_value_error_as_conflict(
        reject_decision, db, decision, current_user.id, comment=payload.comment, via_mcp=channel == "mcp",
    )
    db.commit()
    db.refresh(decision)
    return _decision_to_out(decision)
