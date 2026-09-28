"""
Module: modules.context_strategy._shared

Internal helpers shared by the org-scoped (`router.py`) and project-scoped
(`project_router.py`) routers, which expose an almost identical Strategy
CRUD/lifecycle/comment/file surface differing only in which of
`organization_id`/`project_id` scopes the call and which of this module's
four roles (`strategy_owner`/`strategy_approver`, project-scoped;
`org_strategy_owner`/`org_strategy_approver`, org-scoped — `module.py`)
gates a mutation. Kept here rather than duplicated in both router files,
the same "helper shared by more than one router, hosted once" convention
`modules.decisions.project_router._shared` already follows for that
module's own bucket split — applied here across the two *scope* routers
instead of across per-concern buckets, since Decision Management has no
org/project scope split of its own to mirror directly.

Each literal router file still declares its own FastAPI routes (not built
generically from a shared factory) — matching this codebase's existing
precedent for every other module with both an org- and a project-scoped
router (e.g. `modules.compliance.router`/`project_router`), rather than
inventing a new dynamic-route-building mechanism this codebase has no
other example of.

Phase 2 (Future State) adds the same shape of helpers for the standalone
Future State artefact, under distinct names (`future_state_to_out`,
`get_future_state_in_scope`, `require_future_state_manage_role`,
`require_future_state_approve_permission`) since both artefact types'
helpers now live in this one file — see each function's own docstring for
anything that isn't a pure rename of its Strategy counterpart.
"""

from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.enums import PermissionLevel
from app.models.user import User
from app.modules.context_strategy.enums import FutureStateScope, StrategyScope
from app.modules.context_strategy.models import FutureState, FutureStateVersion, Strategy, StrategyVersion
from app.modules.context_strategy.schemas import FutureStateOut, StrategyOut
from app.modules.context_strategy.service import (
    FUTURE_STATE_ARTEFACT_TYPE,
    STRATEGY_ARTEFACT_TYPE,
    is_future_state_locked,
    is_locked,
)
from app.services.permissions import encode_permission
from app.services.rbac import get_effective_permissions, permission_satisfied, user_satisfies_module_role

MODULE_KEY = "context_strategy"

# Fine-Grained Access Control's unscoped `(strategy, approve_baseline)`
# permission atom — Strategy has no sub-type dimension analogous to
# Decision Management's Decision Type (only the org/project `scope`
# discriminator, which is structural, not a permission sub-type), so this
# stays the plain, unscoped constant `require_approve_permission` checks
# directly, with no per-instance sub-type resolution needed.
STRATEGY_APPROVE_PERMISSION = encode_permission(STRATEGY_ARTEFACT_TYPE, PermissionLevel.APPROVE_BASELINE.value)

# Future State's own unscoped `(future_state, approve_baseline)` permission
# atom — same reasoning as `STRATEGY_APPROVE_PERMISSION` (Future State's
# only scope dimension is structural org/project, not a permission
# sub-type).
FUTURE_STATE_APPROVE_PERMISSION = encode_permission(FUTURE_STATE_ARTEFACT_TYPE, PermissionLevel.APPROVE_BASELINE.value)

_OWNER_ROLE_KEY: dict[StrategyScope, str] = {
    StrategyScope.ORGANIZATION: "org_strategy_owner",
    StrategyScope.PROJECT: "strategy_owner",
}
_APPROVER_ROLE_KEY: dict[StrategyScope, str] = {
    StrategyScope.ORGANIZATION: "org_strategy_approver",
    StrategyScope.PROJECT: "strategy_approver",
}

_FS_OWNER_ROLE_KEY: dict[FutureStateScope, str] = {
    FutureStateScope.ORGANIZATION: "org_future_state_owner",
    FutureStateScope.PROJECT: "future_state_owner",
}
_FS_APPROVER_ROLE_KEY: dict[FutureStateScope, str] = {
    FutureStateScope.ORGANIZATION: "org_future_state_approver",
    FutureStateScope.PROJECT: "future_state_approver",
}


def strategy_to_out(strategy: Strategy, version: StrategyVersion) -> StrategyOut:
    """Merges a `Strategy` identity row with its current `StrategyVersion`'s
    content into the API-facing shape — see `schemas.StrategyOut`'s own
    docstring for why this is always built explicitly rather than via
    `from_attributes`."""
    return StrategyOut(
        id=strategy.id, scope=strategy.scope, organization_id=strategy.organization_id,
        project_id=strategy.project_id, creator_id=strategy.creator_id, is_archived=strategy.is_archived,
        archived_at=strategy.archived_at, archived_by=strategy.archived_by,
        title=version.title, objective=version.objective, current_state=version.current_state,
        desired_future_state=version.desired_future_state, rationale=version.rationale,
        expected_outcomes=version.expected_outcomes, constraints=version.constraints,
        measures_of_success=version.measures_of_success, priority=version.priority,
        time_horizon=version.time_horizon, status=version.status, version_number=version.version_number,
        is_locked=is_locked(version), created_at=strategy.created_at, updated_at=strategy.updated_at,
    )


def get_strategy_in_scope(
    db: Session,
    scope: StrategyScope,
    *,
    organization_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
    strategy_id: uuid.UUID,
) -> Strategy:
    """Loads `strategy_id`, 404ing unless it exists, matches `scope`, and
    belongs to the given `organization_id`/`project_id` — the same
    "doesn't exist" 404 (never a 403 that would confirm cross-tenant
    existence) every other module's own ownership-chain lookup uses."""
    strategy = db.get(Strategy, strategy_id)
    if strategy is None or strategy.scope != scope:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Strategy not found.")
    if scope == StrategyScope.ORGANIZATION and strategy.organization_id != organization_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Strategy not found.")
    if scope == StrategyScope.PROJECT and strategy.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Strategy not found.")
    return strategy


def user_satisfies_owner_role(
    db: Session,
    current_user: User,
    scope: StrategyScope,
    *,
    organization_id: uuid.UUID,
    project_id: uuid.UUID | None,
) -> bool:
    return user_satisfies_module_role(
        db, current_user, MODULE_KEY, _OWNER_ROLE_KEY[scope], organization_id=organization_id, project_id=project_id,
    )


def require_manage_role(
    db: Session,
    current_user: User,
    scope: StrategyScope,
    *,
    organization_id: uuid.UUID,
    project_id: uuid.UUID | None,
) -> None:
    """Gate for create/edit/archive-type actions — satisfied by the scope's
    own `..._owner` module role, which itself composes with server admin
    and `OrgRole.ORG_ADMIN`/`ProjectRole.PROJECT_MANAGER` via
    `user_satisfies_module_role`. Mirrors Decision Management's
    `_require_edit_role` (manage-tier actions there stay flat-role-gated
    only, no Fine-Grained Access Control permission-atom fallback — this
    matches that precedent rather than adding one only for Strategy)."""
    if not user_satisfies_owner_role(db, current_user, scope, organization_id=organization_id, project_id=project_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only a Strategy Owner (or admin/manager) may do this.")


def require_approve_permission(
    db: Session,
    current_user: User,
    scope: StrategyScope,
    *,
    organization_id: uuid.UUID,
    project_id: uuid.UUID | None,
) -> None:
    """Gate for approve/activate/supersede/retire — satisfied by (in
    order): server admin; the scope's own `..._approver` module role
    (which itself composes with `OrgRole.ORG_ADMIN`/`ProjectRole.
    PROJECT_MANAGER`); or a Fine-Grained Access Control custom-role grant
    of the unscoped `(strategy, approve_baseline)` permission atom. The
    permission-atom check additionally covers a caller with a narrower
    custom-role grant but no flat module role — mirroring Decision
    Management's own approve gate, without that module's later sub-type
    scoping (Strategy has no sub-type dimension for this atom to narrow
    against)."""
    if current_user.is_server_admin:
        return
    if user_satisfies_module_role(
        db, current_user, MODULE_KEY, _APPROVER_ROLE_KEY[scope],
        organization_id=organization_id, project_id=project_id,
    ):
        return
    held = get_effective_permissions(db, current_user.id, organization_id=organization_id, project_id=project_id)
    if permission_satisfied(held, STRATEGY_APPROVE_PERMISSION):
        return
    raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient permissions.")


def apply_value_error_as_conflict(fn, *args, **kwargs):
    """Calls a `service.py` lifecycle function, translating its `ValueError`
    (an illegal transition) into an HTTP 409 — mirrors `modules.decisions.
    project_router.workflow._apply_value_error_as_conflict`. Shared as-is
    by both Strategy's and Future State's routers — this helper is already
    generic over the callable, so Phase 2 needed no Future-State-specific
    variant."""
    try:
        return fn(*args, **kwargs)
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc


# --- Future State (Phase 2) -------------------------------------------------


def future_state_to_out(future_state: FutureState, version: FutureStateVersion) -> FutureStateOut:
    """Merges a `FutureState` identity row with its current
    `FutureStateVersion`'s content into the API-facing shape — exact
    mirror of `strategy_to_out`."""
    return FutureStateOut(
        id=future_state.id, scope=future_state.scope, organization_id=future_state.organization_id,
        project_id=future_state.project_id, creator_id=future_state.creator_id,
        is_archived=future_state.is_archived, archived_at=future_state.archived_at,
        archived_by=future_state.archived_by,
        title=version.title, current_state=version.current_state, desired_state=version.desired_state,
        target_date=version.target_date, outcomes=version.outcomes, success_measures=version.success_measures,
        constraints=version.constraints, assumptions=version.assumptions, status=version.status,
        version_number=version.version_number, is_locked=is_future_state_locked(version),
        created_at=future_state.created_at, updated_at=future_state.updated_at,
    )


def get_future_state_in_scope(
    db: Session,
    scope: FutureStateScope,
    *,
    organization_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
    future_state_id: uuid.UUID,
) -> FutureState:
    """Loads `future_state_id`, 404ing unless it exists, matches `scope`,
    and belongs to the given `organization_id`/`project_id` — exact mirror
    of `get_strategy_in_scope`."""
    future_state = db.get(FutureState, future_state_id)
    if future_state is None or future_state.scope != scope:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Future State not found.")
    if scope == FutureStateScope.ORGANIZATION and future_state.organization_id != organization_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Future State not found.")
    if scope == FutureStateScope.PROJECT and future_state.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Future State not found.")
    return future_state


def user_satisfies_future_state_owner_role(
    db: Session,
    current_user: User,
    scope: FutureStateScope,
    *,
    organization_id: uuid.UUID,
    project_id: uuid.UUID | None,
) -> bool:
    return user_satisfies_module_role(
        db, current_user, MODULE_KEY, _FS_OWNER_ROLE_KEY[scope], organization_id=organization_id, project_id=project_id,
    )


def require_future_state_manage_role(
    db: Session,
    current_user: User,
    scope: FutureStateScope,
    *,
    organization_id: uuid.UUID,
    project_id: uuid.UUID | None,
) -> None:
    """Gate for create/edit/archive-type actions on a Future State — exact
    mirror of `require_manage_role`, satisfied by the scope's own
    `..._owner` module role."""
    if not user_satisfies_future_state_owner_role(
        db, current_user, scope, organization_id=organization_id, project_id=project_id
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only a Future State Owner (or admin/manager) may do this.")


def require_future_state_approve_permission(
    db: Session,
    current_user: User,
    scope: FutureStateScope,
    *,
    organization_id: uuid.UUID,
    project_id: uuid.UUID | None,
) -> None:
    """Gate for approve/activate/supersede/retire on a Future State — exact
    mirror of `require_approve_permission`."""
    if current_user.is_server_admin:
        return
    if user_satisfies_module_role(
        db, current_user, MODULE_KEY, _FS_APPROVER_ROLE_KEY[scope],
        organization_id=organization_id, project_id=project_id,
    ):
        return
    held = get_effective_permissions(db, current_user.id, organization_id=organization_id, project_id=project_id)
    if permission_satisfied(held, FUTURE_STATE_APPROVE_PERMISSION):
        return
    raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient permissions.")
