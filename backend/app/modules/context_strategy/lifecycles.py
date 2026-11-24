"""
Module: modules.context_strategy.lifecycles

The state paths of Context & Strategy's record types as `LifecycleDefinition`s, so a project can turn off an optional
state and an organisation can require it (`services.lifecycles`).

Responsibilities:
- Build each definition from the transition table the type's own transition function enforces (one source), with the
  formal labels of `labels.py`.
- Declare the optional states: Triaged (Pain Point), Proposed and Under review (Strategy, Future State), Proposed
  (Guiding Principle) and Investigating (Open Question). Approved is gated on every approval type.

Dependencies: `service` (the tables), `labels`, `services.lifecycles`.
"""

from __future__ import annotations

from app.modules.context_strategy import service as s
from app.modules.context_strategy.labels import (
    LIFECYCLE_STATUS_LABEL,
    OPEN_QUESTION_STATUS_LABEL,
    PAIN_POINT_STATUS_LABEL,
)
from app.modules.registry import LifecycleDefinition
from app.services.lifecycles import table_from_enum

LIFECYCLES: dict[str, LifecycleDefinition] = {
    s.STRATEGY_ARTEFACT_TYPE: LifecycleDefinition(
        label="Strategy", path=("draft", "proposed", "under_review", "approved", "active"),
        transitions=table_from_enum(s._ALLOWED_TRANSITIONS), labels=LIFECYCLE_STATUS_LABEL,
        optional=("proposed", "under_review"), gated=("approved",),
    ),
    s.FUTURE_STATE_ARTEFACT_TYPE: LifecycleDefinition(
        label="Future State", path=("draft", "proposed", "under_review", "approved", "active"),
        transitions=table_from_enum(s._FS_ALLOWED_TRANSITIONS), labels=LIFECYCLE_STATUS_LABEL,
        optional=("proposed", "under_review"), gated=("approved",),
    ),
    s.GUIDING_PRINCIPLE_ARTEFACT_TYPE: LifecycleDefinition(
        label="Guiding Principle", path=("draft", "proposed", "approved", "active"),
        transitions=table_from_enum(s._GP_ALLOWED_TRANSITIONS), labels=LIFECYCLE_STATUS_LABEL,
        optional=("proposed",), gated=("approved",),
    ),
    s.PAIN_POINT_ARTEFACT_TYPE: LifecycleDefinition(
        label="Pain Point", path=("submitted", "triaged", "accepted", "addressed", "closed"),
        transitions=table_from_enum(s._PP_ALLOWED_TRANSITIONS), labels=PAIN_POINT_STATUS_LABEL,
        optional=("triaged",),
    ),
    s.OPEN_QUESTION_ARTEFACT_TYPE: LifecycleDefinition(
        label="Open Question", path=("open", "investigating", "ready_for_decision", "resolved"),
        transitions=table_from_enum(s._OQ_ALLOWED_TRANSITIONS), labels=OPEN_QUESTION_STATUS_LABEL,
        optional=("investigating",),
    ),
}
