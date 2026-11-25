"""
Module: modules.product_feedback.lifecycles

The Enhancement request state path as a `LifecycleDefinition`, so a project can turn off Under review and an
organisation can require it (`services.lifecycles`).

Responsibilities:
- Build the definition from `service.ALLOWED_TRANSITIONS` (one source) with the formal labels.
- Declare Under review optional.

Dependencies: `service`, `labels`, `services.lifecycles`.
"""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.models.project import Project
from app.models.user import User
from app.modules.product_feedback import service as s
from app.modules.product_feedback.labels import REQUEST_STATUS_LABEL
from app.modules.registry import LifecycleDefinition
from app.services.lifecycles import table_from_enum


def _entry_guard(db: Session, user: User, project: Project, record_id: uuid.UUID, state: str) -> None:
    """Refuses (403) when `user` may not move an Enhancement request into `state`: every step needs the triager role.

    Raises:
        HTTPException: 403 when the person lacks the role.
    """
    from app.modules.product_feedback import _shared

    _shared.require_request_manage(db, user, _shared.RecordOwner.of_project(project))


LIFECYCLES: dict[str, LifecycleDefinition] = {
    s.REQUEST_ARTEFACT_TYPE: LifecycleDefinition(
        label="Enhancement request", path=("new", "under_review", "accepted", "delivered"),
        transitions=table_from_enum(s.ALLOWED_TRANSITIONS), labels=REQUEST_STATUS_LABEL,
        optional=("under_review",), entry_guard=_entry_guard,
    ),
}
