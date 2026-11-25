"""
Module: modules.decisions.health

Reports the Decision's progress to the governance health view (`modules.seams.HealthProvider`): the share of live
decisions that are approved.

Responsibilities:
- Count the project's own decisions by status in one grouped statement. Archived decisions, and rejected and
  superseded ones, are left out of the total: a decision that was set aside or replaced is not unfinished work.

Dependencies: `models`, `enums`, `services.health_core`.
"""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.modules.decisions.enums import DecisionStatus
from app.modules.decisions.models import Decision
from app.modules.decisions.service import DECISION_ARTEFACT_TYPE
from app.modules.seams import HealthMeasure, HealthProvider
from app.services.health_core import measure_from_counts, status_counts

_LIVE = {DecisionStatus.DRAFT.value, DecisionStatus.PROPOSED.value, DecisionStatus.UNDER_REVIEW.value, DecisionStatus.APPROVED.value}


def measure_decisions(db: Session, project_id: uuid.UUID) -> HealthMeasure:
    """The project's live decisions, of which the approved ones are done.

    Args:
        db: An active database session (read only).
        project_id: The project.

    Returns:
        The total of live decisions and how many are approved.
    """
    counts = status_counts(db, Decision.status, Decision.project_id == project_id, Decision.is_archived.is_(False))
    return measure_from_counts(counts, _LIVE, {DecisionStatus.APPROVED.value})


HEALTH_PROVIDERS: tuple[HealthProvider, ...] = (
    HealthProvider(
        key="decision", label="Decisions", artefact_type=DECISION_ARTEFACT_TYPE, kind="completion", measure=measure_decisions,
    ),
)
