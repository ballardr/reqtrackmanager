"""
Module: modules.risk_management.lifecycles

The Risk state path as a `LifecycleDefinition`, so a project can turn off the treatment steps and an organisation can
require them (`services.lifecycles`).

Responsibilities:
- Build the definition from `service.RISK_ALLOWED_TRANSITIONS` (one source) with the formal labels.
- Declare Treatment planned and Treatment in progress optional. Assessed stays on the path because it carries the
  rating the rest of the lifecycle reads; the checks of a state a move passes over still run
  (`service.transition_risk`), so turning a step off never removes an owner, a strategy or a rating requirement.
- Declare Accepted gated (its own role and acceptance criteria).

Dependencies: `service`, `labels`, `services.lifecycles`.
"""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.models.project import Project
from app.models.user import User
from app.modules.registry import LifecycleDefinition
from app.modules.risk_management import service as s
from app.modules.risk_management.labels import RISK_STATUS_LABEL
from app.services.lifecycles import table_from_enum


def _entry_guard(db: Session, user: User, project: Project, record_id: uuid.UUID, state: str) -> None:
    """Refuses (403) when `user` may not move a Risk into `state`: every step of the main path needs the Risk Manager
    role (Accepted, which needs the acceptor role, is gated and never passed over).

    Raises:
        HTTPException: 403 when the person lacks the role.
    """
    from app.modules.risk_management import _shared

    _shared.require_risk_manage(db, user, project)


LIFECYCLES: dict[str, LifecycleDefinition] = {
    s.RISK_ARTEFACT_TYPE: LifecycleDefinition(
        label="Risk",
        path=("identified", "assessed", "treatment_planned", "treatment_in_progress", "mitigated", "closed"),
        transitions=table_from_enum(s.RISK_ALLOWED_TRANSITIONS), labels=RISK_STATUS_LABEL,
        optional=("treatment_planned", "treatment_in_progress"), gated=("accepted",), entry_guard=_entry_guard,
    ),
}
