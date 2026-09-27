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

`approve`/`reject` were Fine-Grained Access Control Phase 4's second
migration (`docs/plans/core-fine-grained-access-control-plan.md`) — the
first live consumer of `require_permission` (Phase 2) as a FastAPI
dependency, replacing the previous flat `require_module_role("decisions",
"decision_approver")` gate, checking the unscoped `(decision,
approve_baseline)` permission atom.

Phase 7 narrows this further to a **sub-type-scoped** check: `(decision,
approve_baseline, subtype=<this decision's own Decision Type name>)`,
via `_require_approve_permission_for_decision` below. Because the
sub-type is per-instance data (the loaded `Decision` row's own
`decision_type_id`), not a path parameter, this can no longer go through
`require_permission`'s FastAPI-dependency form — see that factory's own
docstring for why — so it is called directly from inside the route body,
after `_get_decision_in_project_for_update` loads the row, instead of as
a leading `Depends`. A caller holding the flat, unscoped
`decision_approver`/`(decision, approve_baseline)` grant is unaffected:
`permission_satisfied`'s wildcard rule lets that unscoped grant satisfy
any specific sub-type, so today's flat-approval behaviour is unchanged
for every existing holder with zero configuration (Design Principle 1).
`_require_view` still runs first (module-enabled/project-membership,
404) via its own leading `Depends`, exactly as every sibling endpoint in
this package already does.
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
from app.services.permissions import encode_permission
from app.services.rbac import get_effective_permissions, permission_satisfied, require_ai_approvals_enabled

router = APIRouter(tags=["decisions-workflow"])


def _require_approve_permission_for_decision(
    db: Session, current_user: User, project_id: UUID, decision: Decision,
) -> None:
    """Sub-type-scoped `(decision, approve_baseline, subtype=<this
    decision's own Decision Type name>)` check (Fine-Grained Access
    Control Phase 7) — see this module's own docstring above for why this
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
    current_user: User = Depends(_require_view),
    db: Session = Depends(get_db),
    channel: str = Depends(get_request_channel),
):
    """Formally approves a Decision (`UNDER_REVIEW` -> `APPROVED`) — gated
    by the `(decision, approve_baseline, subtype=<this decision's own
    Decision Type>)` permission atom (Fine-Grained Access Control Phase 7
    — see this module's own docstring). `_require_view` (module-enabled/
    project-membership, 404) is declared first so it is resolved before
    `_require_approve_permission_for_decision`'s 403, matching every
    sibling endpoint in this package.

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
    _require_approve_permission_for_decision(db, current_user, project_id, decision)
    _apply_value_error_as_conflict(
        approve_decision, db, decision, current_user.id, comment=payload.comment, via_mcp=channel == "mcp",
    )
    db.commit()
    db.refresh(decision)
    return _decision_to_out(decision)


@router.post("/{decision_id}/reject", response_model=DecisionOut)
def reject_decision_endpoint(
    project_id: UUID, decision_id: UUID, payload: DecisionTransitionRequest,
    current_user: User = Depends(_require_view),
    db: Session = Depends(get_db),
    channel: str = Depends(get_request_channel),
):
    """Formally rejects a Decision (`PROPOSED`/`UNDER_REVIEW` -> `REJECTED`).
    Rejection requires a comment — mirrors `record_review_outcome`'s
    mandatory-comment-on-`FAILED` rule (`routers.requirements.py`) and
    `reject_requirement`'s mandatory `decision_note`
    (`modules.compliance.project_router`): a rejection must never appear
    with no indication of why. Gated by the same sub-type-scoped
    permission check as `approve` (Fine-Grained Access Control Phase 7) —
    see `approve_decision_endpoint`'s docstring above.

    No longer marked `APPROVAL_ACTION_ROUTE_EXTRA` (2026-09-22) — see
    `approve_decision_endpoint`'s docstring above; gated the same way when
    reached through the MCP server."""
    if not (payload.comment or "").strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A comment is required to reject a Decision.")
    project = db.get(Project, project_id)
    if channel == "mcp":
        require_ai_approvals_enabled(db, project)
    decision = _get_decision_in_project_for_update(db, project_id, decision_id)
    _require_approve_permission_for_decision(db, current_user, project_id, decision)
    _apply_value_error_as_conflict(
        reject_decision, db, decision, current_user.id, comment=payload.comment, via_mcp=channel == "mcp",
    )
    db.commit()
    db.refresh(decision)
    return _decision_to_out(decision)
