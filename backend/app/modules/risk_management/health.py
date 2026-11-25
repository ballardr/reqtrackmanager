"""
Module: modules.risk_management.health

Reports the Risk's progress to the governance health view (`modules.seams.HealthProvider`): the share of risks that have
reached a handled outcome.

Responsibilities:
- Count the project's own risks by the status of their current version in one grouped statement. A risk is handled once it
  is mitigated, accepted, transferred, avoided or closed; a rejected risk and an archived one are left out of the total.
  A realised risk stays in the total until it is closed, because it has happened and is not yet dealt with.

Dependencies: `models`, `enums`, `services.health_core`.
"""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.modules.risk_management.enums import RiskStatus
from app.modules.risk_management.models import Risk, RiskVersion
from app.modules.risk_management.service import RISK_ARTEFACT_TYPE
from app.modules.seams import HealthMeasure, HealthProvider
from app.services.health_core import measure_from_counts, versioned_status_counts

_HANDLED = {
    RiskStatus.MITIGATED.value, RiskStatus.ACCEPTED.value, RiskStatus.TRANSFERRED.value, RiskStatus.AVOIDED.value,
    RiskStatus.CLOSED.value,
}
_COUNTED = _HANDLED | {
    RiskStatus.IDENTIFIED.value, RiskStatus.ASSESSED.value, RiskStatus.TREATMENT_PLANNED.value,
    RiskStatus.TREATMENT_IN_PROGRESS.value, RiskStatus.REALISED.value,
}


def measure_risks(db: Session, project_id: uuid.UUID) -> HealthMeasure:
    """The project's live risks, of which the handled ones are done.

    Args:
        db: An active database session (read only).
        project_id: The project.

    Returns:
        The total of counted risks and how many are handled.
    """
    counts = versioned_status_counts(
        db, Risk, RiskVersion, "risk_id", RiskVersion.status, Risk.project_id == project_id, Risk.is_archived.is_(False),
    )
    return measure_from_counts(counts, _COUNTED, _HANDLED)


HEALTH_PROVIDERS: tuple[HealthProvider, ...] = (
    HealthProvider(key="risk", label="Risks", artefact_type=RISK_ARTEFACT_TYPE, kind="completion", measure=measure_risks),
)
