"""
Module: modules.context_strategy.lifecycles

The state paths of Context & Strategy's record types as `LifecycleDefinition`s, so a project can turn off an optional
state and an organisation can require it (`services.lifecycles`).

Responsibilities:
- Build each definition from the transition table the type's own transition function enforces (one source), with the
  formal labels of `labels.py`.
- Declare the optional states: Triaged (Pain Point), Proposed and Under review (Strategy, Future State), Proposed
  (Guiding Principle) and Investigating (Open Question). Approved is gated on every approval type.
- Check, for a skip of steps, that the person may enter each step passed over as the type's own move endpoints require
  (the `_*_guard` functions).

Dependencies: `service` (the tables), `labels`, `services.lifecycles`, `project_router` (the endpoints' own checks).
"""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.models.project import Project
from app.models.user import User
from app.modules.context_strategy import service as s
from app.modules.context_strategy.labels import (
    LIFECYCLE_STATUS_LABEL,
    OPEN_QUESTION_STATUS_LABEL,
    PAIN_POINT_STATUS_LABEL,
)
from app.modules.context_strategy.models import FutureState, GuidingPrinciple, Strategy
from app.modules.registry import LifecycleDefinition
from app.services.lifecycles import table_from_enum


def _strategy_guard(db: Session, user: User, project: Project, record_id: uuid.UUID, state: str) -> None:
    """Refuses (403) when `user` may not move the Strategy into `state`: its creator or a manager may propose and
    submit for review, the approver permission is needed from approval on.

    Raises:
        HTTPException: 403 when the person lacks the right.
    """
    from app.modules.context_strategy import project_router as routes
    from app.modules.context_strategy.models import Strategy

    strategy = db.get(Strategy, record_id)
    if strategy is None:
        return
    if state in ("proposed", "under_review"):
        routes._require_creator_or_manage(db, user, project, strategy)
    else:
        routes.require_approve_permission(
            db, user, routes._SCOPE, organization_id=project.organization_id, project_id=project.id,
        )


def _future_state_guard(db: Session, user: User, project: Project, record_id: uuid.UUID, state: str) -> None:
    """The Future State counterpart of `_strategy_guard`."""
    from app.modules.context_strategy import project_router as routes
    from app.modules.context_strategy.models import FutureState

    future_state = db.get(FutureState, record_id)
    if future_state is None:
        return
    if state in ("proposed", "under_review"):
        routes._require_fs_creator_or_manage(db, user, project, future_state)
    else:
        routes.require_future_state_approve_permission(
            db, user, routes._FS_SCOPE, organization_id=project.organization_id, project_id=project.id,
        )


def _guiding_principle_guard(db: Session, user: User, project: Project, record_id: uuid.UUID, state: str) -> None:
    """The Guiding Principle counterpart of `_strategy_guard`."""
    from app.modules.context_strategy import project_router as routes
    from app.modules.context_strategy.models import GuidingPrinciple

    guiding_principle = db.get(GuidingPrinciple, record_id)
    if guiding_principle is None:
        return
    if state == "proposed":
        routes._require_gp_creator_or_manage(db, user, project, guiding_principle)
    else:
        routes.require_guiding_principle_approve_permission(
            db, user, routes._GP_SCOPE, organization_id=project.organization_id, project_id=project.id,
        )


def _pain_point_guard(db: Session, user: User, project: Project, record_id: uuid.UUID, state: str) -> None:
    """Refuses (403) when `user` may not decide Pain Points: every move after submission needs the decide tier."""
    from app.modules.context_strategy import project_router as routes

    routes.require_pain_point_decide_permission(
        db, user, organization_id=project.organization_id, project_id=project.id,
    )


def _open_question_guard(db: Session, user: User, project: Project, record_id: uuid.UUID, state: str) -> None:
    """Refuses (403) when `user` may not move the Open Question into `state`: the manage role for investigating and
    ready for decision, the separate resolve permission for resolved."""
    from app.modules.context_strategy import project_router as routes

    if state == "resolved":
        routes.require_open_question_resolve_permission(
            db, user, organization_id=project.organization_id, project_id=project.id,
        )
    else:
        routes.require_open_question_manage_role(
            db, user, organization_id=project.organization_id, project_id=project.id,
        )


LIFECYCLES: dict[str, LifecycleDefinition] = {
    s.STRATEGY_ARTEFACT_TYPE: LifecycleDefinition(
        label="Strategy", path=("draft", "proposed", "under_review", "approved", "active"),
        transitions=table_from_enum(s._ALLOWED_TRANSITIONS), labels=LIFECYCLE_STATUS_LABEL,
        optional=("proposed", "under_review"), gated=("approved",), entry_guard=_strategy_guard,
        record_model=Strategy,
    ),
    s.FUTURE_STATE_ARTEFACT_TYPE: LifecycleDefinition(
        label="Future State", path=("draft", "proposed", "under_review", "approved", "active"),
        transitions=table_from_enum(s._FS_ALLOWED_TRANSITIONS), labels=LIFECYCLE_STATUS_LABEL,
        optional=("proposed", "under_review"), gated=("approved",), entry_guard=_future_state_guard,
        record_model=FutureState,
    ),
    s.GUIDING_PRINCIPLE_ARTEFACT_TYPE: LifecycleDefinition(
        label="Guiding Principle", path=("draft", "proposed", "approved", "active"),
        transitions=table_from_enum(s._GP_ALLOWED_TRANSITIONS), labels=LIFECYCLE_STATUS_LABEL,
        optional=("proposed",), gated=("approved",), entry_guard=_guiding_principle_guard,
        record_model=GuidingPrinciple,
    ),
    s.PAIN_POINT_ARTEFACT_TYPE: LifecycleDefinition(
        label="Pain Point", path=("submitted", "triaged", "accepted", "addressed", "closed"),
        transitions=table_from_enum(s._PP_ALLOWED_TRANSITIONS), labels=PAIN_POINT_STATUS_LABEL,
        optional=("triaged",), entry_guard=_pain_point_guard,
    ),
    s.OPEN_QUESTION_ARTEFACT_TYPE: LifecycleDefinition(
        label="Open Question", path=("open", "investigating", "ready_for_decision", "resolved"),
        transitions=table_from_enum(s._OQ_ALLOWED_TRANSITIONS), labels=OPEN_QUESTION_STATUS_LABEL,
        optional=("investigating",), entry_guard=_open_question_guard,
    ),
}
