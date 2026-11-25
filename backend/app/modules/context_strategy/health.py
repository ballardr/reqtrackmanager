"""
Module: modules.context_strategy.health

Reports Context & Strategy progress to the governance health view (`modules.seams.HealthProvider`): the share of a
project's Strategies, Future States and Guiding Principles that are approved or active, and the Open Questions still
outstanding.

Responsibilities:
- Count each type's project-scoped records in one grouped statement (the status of Strategy, Future State and Guiding
  Principle is on the current version row; an Open Question's is on the record). Organisation-scoped records belong to
  no project and are not counted. Archived records, and superseded or retired ones, are left out of a completion total;
  an Open Question that is resolved or withdrawn is done.

Dependencies: `models`, `enums`, `services.health_core`.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session

from app.modules.context_strategy.enums import OpenQuestionStatus
from app.modules.context_strategy.models import (
    FutureState,
    FutureStateVersion,
    GuidingPrinciple,
    GuidingPrincipleVersion,
    OpenQuestion,
    Strategy,
    StrategyVersion,
)
from app.modules.context_strategy.service import (
    FUTURE_STATE_ARTEFACT_TYPE,
    GUIDING_PRINCIPLE_ARTEFACT_TYPE,
    OPEN_QUESTION_ARTEFACT_TYPE,
    STRATEGY_ARTEFACT_TYPE,
)
from app.modules.seams import HealthMeasure, HealthProvider
from app.services.health_core import measure_from_counts, status_counts, versioned_status_counts

#: The statuses a Strategy, Future State or Guiding Principle is still live in, and the ones that are settled.
_SETTLED = {"approved", "active"}
_LIVE = _SETTLED | {"draft", "proposed", "under_review"}

_OPEN_QUESTION_DONE = {OpenQuestionStatus.RESOLVED.value, OpenQuestionStatus.WITHDRAWN.value}
_OPEN_QUESTION_COUNTED = _OPEN_QUESTION_DONE | {
    OpenQuestionStatus.OPEN.value, OpenQuestionStatus.INVESTIGATING.value, OpenQuestionStatus.READY_FOR_DECISION.value,
}


def _versioned(record_model: Any, version_model: Any, fk: str) -> Callable[[Session, uuid.UUID], HealthMeasure]:
    """A measure for a project-scoped type whose status is on its current version row."""

    def measure(db: Session, project_id: uuid.UUID) -> HealthMeasure:
        counts = versioned_status_counts(
            db, record_model, version_model, fk, version_model.status,
            record_model.project_id == project_id, record_model.is_archived.is_(False),
        )
        return measure_from_counts(counts, _LIVE, _SETTLED)

    return measure


def measure_open_questions(db: Session, project_id: uuid.UUID) -> HealthMeasure:
    """The project's open questions, of which the resolved and withdrawn ones are done.

    Args:
        db: An active database session (read only).
        project_id: The project.

    Returns:
        The total of live open questions and how many are no longer outstanding.
    """
    counts = status_counts(db, OpenQuestion.status, OpenQuestion.project_id == project_id, OpenQuestion.is_archived.is_(False))
    return measure_from_counts(counts, _OPEN_QUESTION_COUNTED, _OPEN_QUESTION_DONE)


HEALTH_PROVIDERS: tuple[HealthProvider, ...] = (
    HealthProvider(
        key="strategy", label="Strategies", artefact_type=STRATEGY_ARTEFACT_TYPE, kind="completion",
        measure=_versioned(Strategy, StrategyVersion, "strategy_id"),
    ),
    HealthProvider(
        key="future_state", label="Future states", artefact_type=FUTURE_STATE_ARTEFACT_TYPE, kind="completion",
        measure=_versioned(FutureState, FutureStateVersion, "future_state_id"),
    ),
    HealthProvider(
        key="guiding_principle", label="Guiding principles", artefact_type=GUIDING_PRINCIPLE_ARTEFACT_TYPE, kind="completion",
        measure=_versioned(GuidingPrinciple, GuidingPrincipleVersion, "guiding_principle_id"),
    ),
    HealthProvider(
        key="open_question", label="Open questions", artefact_type=OPEN_QUESTION_ARTEFACT_TYPE, kind="outstanding",
        measure=measure_open_questions,
    ),
)
