"""
Module: modules.decisions.lifecycles

The Decision state path as a `LifecycleDefinition`, so a project can turn off Proposed and Under review and an
organisation can require them (`services.lifecycles`).

Responsibilities:
- Build the definition from the transition table `service.transition` enforces (one source) with the formal labels.
- Declare Proposed and Under review optional and Approved gated: turning the review steps off leaves Draft to
  Approved behind the approver's permission and comment.
- Check, for a skip of steps, that the person may enter each step passed over as the Decision's own move endpoints
  require (`_entry_guard`).

Dependencies: `service`, `labels`, `services.lifecycles`, `project_router.workflow` (the endpoints' own checks).
"""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.models.project import Project
from app.models.user import User
from app.modules.decisions import service as s
from app.modules.decisions.labels import DECISION_STATUS_LABEL
from app.modules.registry import LifecycleDefinition
from app.services.lifecycles import table_from_enum


def _entry_guard(db: Session, user: User, project: Project, record_id: uuid.UUID, state: str) -> None:
    """Refuses (403) when `user` may not move the Decision into `state`: the owner or an editor may propose and submit
    for review, the approver permission is needed for approval.

    Raises:
        HTTPException: 403 when the person lacks the right.
    """
    from app.modules.decisions.models import Decision
    from app.modules.decisions.project_router import workflow

    decision = db.get(Decision, record_id)
    if decision is None:
        return
    if state == "approved":
        workflow._require_approve_permission_for_decision(db, user, project.id, decision)
    else:
        workflow._require_owner_of_decision_or_role(db, user, project, decision)


LIFECYCLES: dict[str, LifecycleDefinition] = {
    s.DECISION_ARTEFACT_TYPE: LifecycleDefinition(
        label="Decision", path=("draft", "proposed", "under_review", "approved"),
        transitions=table_from_enum(s._ALLOWED_TRANSITIONS), labels=DECISION_STATUS_LABEL,
        optional=("proposed", "under_review"), gated=("approved",), entry_guard=_entry_guard,
    ),
}
