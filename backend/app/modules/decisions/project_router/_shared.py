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
from app.modules.decisions.edits import is_locked, user_is_decision_owner
from app.modules.decisions.models import Decision
from app.services.rbac import require_project_module_enabled

# Factory called once, at router-definition time — same convention as
# every other module router in this codebase (`modules.compliance.
# project_router`'s own comment on this).
_require_view = require_project_module_enabled("decisions")

# A Decision's content fields become immutable once approved or superseded (§13/10.6); the rule lives in
# `edits` so the record-table import applies the same one.
_is_locked = is_locked


def _get_decision_in_project(db: Session, project_id: UUID, decision_id: UUID) -> Decision:
    decision = db.get(Decision, decision_id)
    if decision is None or decision.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Decision not found.")
    return decision


_user_satisfies_decision_owner = user_is_decision_owner


def _require_edit_role(db: Session, current_user: User, project: Project) -> None:
    if not _user_satisfies_decision_owner(db, current_user, project):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only a Decision Owner (or project manager) may do this.")
