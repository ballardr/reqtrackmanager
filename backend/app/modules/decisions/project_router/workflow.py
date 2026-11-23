"""
Module: modules.decisions.project_router.workflow

Lifecycle transitions: propose/submit-for-review/approve/reject. `approve`/
`reject` carry the AI-approval MCP gate (`require_ai_approvals_enabled`) and a
sub-type-scoped permission check `(decision, approve_baseline,
subtype=<Decision Type name>)`, called from the route body once the row is
loaded; an unscoped holder satisfies any sub-type. Also home for
`_apply_value_error_as_conflict`, used by `relationships.py`.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_request_channel
from app.models.enums import PermissionLevel
from app.models.project import Project
from app.models.user import User
from app.modules.decisions.models import Decision, DecisionTypeDefinition
from app.modules.decisions.project_router._shared import _get_decision_in_project, _require_edit_role, _require_view
from app.modules.decisions.project_router.core import _decision_to_out
from app.modules.decisions.schemas import DecisionOut, DecisionTransitionRequest
from app.modules.decisions.service import (
    DECISION_ARTEFACT_TYPE,
    approve_decision,
    propose_decision,
    reject_decision,
    submit_decision_for_review,
)
from app.services.lookups import project_or_404
from app.services.permissions import encode_permission
from app.services.principals import is_principal_member, principal_ref
from app.services.rbac import get_effective_permissions, permission_satisfied, require_ai_approvals_enabled

router = APIRouter(tags=["decisions-workflow"])


def _require_approve_permission_for_decision(
    db: Session, current_user: User, project_id: UUID, decision: Decision,
) -> None:
    """Sub-type-scoped `(decision, approve_baseline, subtype=<this
    decision's own Decision Type name>)` check (Fine-Grained Access
    Control) — see this module's own docstring above for why this
    is a direct `get_effective_permissions`/`permission_satisfied` call
    rather than a `require_permission` `Depends`. Server admin bypasses,
    consistent with every existing `require_*` check in `rbac.py`."""
    if current_user.is_server_admin:
        return
    decision_type = db.get(DecisionTypeDefinition, decision.decision_type_id)
    subtype = decision_type.name if decision_type is not None else None
    held = get_effective_permissions(db, current_user.id, project_id=project_id)
    required = encode_permission(DECISION_ARTEFACT_TYPE, PermissionLevel.APPROVE_BASELINE.value, subtype)
    if not permission_satisfied(held, required):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient permissions.")


def _require_owner_of_decision_or_role(db: Session, current_user: User, project: Project, decision: Decision) -> None:
    """Gate for `propose`/`submit-for-review` — see this package's own
    `__init__.py` docstring for why this is a distinct, looser gate than
    `_require_edit_role`. The owner is a principal, so the caller passes when
    they are the owner user or an effective member of the owner group; a group
    confers no right beyond this (they still need project access, checked
    before this runs, and the approve permission is unchanged)."""
    if is_principal_member(db, principal_ref(decision.owner_type, decision.owner_id), current_user.id):
        return
    _require_edit_role(db, current_user, project)


def _get_decision_in_project_for_update(db: Session, project_id: UUID, decision_id: UUID) -> Decision:
    """Row-locked variant of `_get_decision_in_project`, for `approve`/`reject`
    only: two concurrent decide-type calls would otherwise both read the
    pre-transition status, pass the transition check and apply their side
    effects. The lock makes the second call check against the committed result."""
    decision = db.scalar(select(Decision).where(Decision.id == decision_id).with_for_update())
    if decision is None or decision.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Decision not found.")
    return decision


def _apply_value_error_as_conflict(fn, *args, **kwargs):
    """Calls a `service.py` function, translating its `ValueError`
    (that layer's own "validation failed" convention) into an HTTP 409 —
    the translation every one of `service.py`'s own docstrings names as
    the router's responsibility."""
    try:
        return fn(*args, **kwargs)
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc


@router.post("/{decision_id}/propose", response_model=DecisionOut)
def propose_decision_endpoint(
    project_id: UUID, decision_id: UUID,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    project = project_or_404(db, project_id)
    decision = _get_decision_in_project(db, project_id, decision_id)
    _require_owner_of_decision_or_role(db, current_user, project, decision)
    _apply_value_error_as_conflict(propose_decision, db, decision, current_user.id)
    db.commit()
    db.refresh(decision)
    return _decision_to_out(db, decision)


@router.post("/{decision_id}/submit-for-review", response_model=DecisionOut)
def submit_decision_for_review_endpoint(
    project_id: UUID, decision_id: UUID,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    project = project_or_404(db, project_id)
    decision = _get_decision_in_project(db, project_id, decision_id)
    _require_owner_of_decision_or_role(db, current_user, project, decision)
    _apply_value_error_as_conflict(submit_decision_for_review, db, decision, current_user.id)
    db.commit()
    db.refresh(decision)
    return _decision_to_out(db, decision)


@router.post("/{decision_id}/approve", response_model=DecisionOut)
def approve_decision_endpoint(
    project_id: UUID, decision_id: UUID, payload: DecisionTransitionRequest,
    current_user: User = Depends(_require_view),
    db: Session = Depends(get_db),
    channel: str = Depends(get_request_channel),
):
    """Formally approves a Decision (`UNDER_REVIEW` -> `APPROVED`), gated by the
    `(decision, approve_baseline, subtype=<Decision Type>)` permission.
    `_require_view` (404) is declared first so it resolves before the 403.
    MCP-reachable; through the MCP server (`channel == "mcp"`) it also
    requires the project and its organisation to enable AI approval
    (`require_ai_approvals_enabled`). A plain UI/API call is unaffected."""
    project = project_or_404(db, project_id)
    if channel == "mcp":
        require_ai_approvals_enabled(db, project)
    decision = _get_decision_in_project_for_update(db, project_id, decision_id)
    _require_approve_permission_for_decision(db, current_user, project_id, decision)
    _apply_value_error_as_conflict(
        approve_decision, db, decision, current_user.id, comment=payload.comment, via_mcp=channel == "mcp",
    )
    db.commit()
    db.refresh(decision)
    return _decision_to_out(db, decision)


@router.post("/{decision_id}/reject", response_model=DecisionOut)
def reject_decision_endpoint(
    project_id: UUID, decision_id: UUID, payload: DecisionTransitionRequest,
    current_user: User = Depends(_require_view),
    db: Session = Depends(get_db),
    channel: str = Depends(get_request_channel),
):
    """Formally rejects a Decision (`PROPOSED`/`UNDER_REVIEW` -> `REJECTED`).
    A comment is mandatory, so a rejection always records why. Gated like
    `approve` (sub-type-scoped permission, and `require_ai_approvals_enabled`
    when reached through the MCP server)."""
    if not (payload.comment or "").strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A comment is required to reject a Decision.")
    project = project_or_404(db, project_id)
    if channel == "mcp":
        require_ai_approvals_enabled(db, project)
    decision = _get_decision_in_project_for_update(db, project_id, decision_id)
    _require_approve_permission_for_decision(db, current_user, project_id, decision)
    _apply_value_error_as_conflict(
        reject_decision, db, decision, current_user.id, comment=payload.comment, via_mcp=channel == "mcp",
    )
    db.commit()
    db.refresh(decision)
    return _decision_to_out(db, decision)
