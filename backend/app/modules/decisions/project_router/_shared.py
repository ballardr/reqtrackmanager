"""
Module: modules.decisions.project_router._shared

Internal helpers shared by several bucket modules of the Decision
Management module's project-scoped router package (docs/decisions.md's
"Split `decisions/project_router.py` into a package" entry) — the
module-role/module-enabled dependency factory (`_require_view`), the
Decision ownership-chain lookup, the `decision_owner`-or-project-manager
edit-role gate, and the content-lock check. Not a router itself — no
`@router` routes live here. Every name here is used by three or more
sibling bucket modules (verified by call-site grep before this split); a
helper used by only one or two buckets instead stayed local to (or was
hosted/imported between) those buckets, per this package's own split
convention (mirroring `modules.compliance.project_router._shared`).
"""

from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.project import Project
from app.models.user import User
from app.modules.decisions.enums import DecisionStatus
from app.modules.decisions.models import Decision
from app.services.rbac import require_project_module_enabled, user_satisfies_module_role

# Factory called once, at router-definition time — same convention as
# every other module router in this codebase (`modules.compliance.
# project_router`'s own comment on this).
_require_view = require_project_module_enabled("decisions")

# A Decision's content fields become immutable once it reaches either of
# these statuses (source overview §13/10.6) — see the package's own
# `__init__.py` docstring.
_LOCKED_STATUSES = frozenset({DecisionStatus.APPROVED, DecisionStatus.SUPERSEDED})


def _is_locked(decision: Decision) -> bool:
    return decision.status in _LOCKED_STATUSES


def _get_decision_in_project(db: Session, project_id: UUID, decision_id: UUID) -> Decision:
    decision = db.get(Decision, decision_id)
    if decision is None or decision.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Decision not found.")
    return decision


def _user_satisfies_decision_owner(db: Session, current_user: User, project: Project) -> bool:
    return user_satisfies_module_role(
        db, current_user, "decisions", "decision_owner",
        organization_id=project.organization_id, project_id=project.id,
    )


def _require_edit_role(db: Session, current_user: User, project: Project) -> None:
    if not _user_satisfies_decision_owner(db, current_user, project):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only a Decision Owner (or project manager) may do this.")
