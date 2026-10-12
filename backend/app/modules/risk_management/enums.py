"""
Module: modules.risk_management.enums

Risk Management's own vocabulary (docs/plans/module-03-risk-management-plan.md
Phase 0 resolutions 4 and 9), kept in this package rather than core.
"""

from __future__ import annotations

import enum


class RiskStatus(str, enum.Enum):
    """Lifecycle states of a `Risk` (overview §11.4).

    The main line is `IDENTIFIED -> ASSESSED -> TREATMENT_PLANNED ->
    TREATMENT_IN_PROGRESS -> MITIGATED -> CLOSED`. `ACCEPTED`, `TRANSFERRED`,
    `AVOIDED`, `REALISED` and `REJECTED` are alternative outcomes that lead to
    `CLOSED`. The legal moves are `service.RISK_ALLOWED_TRANSITIONS`.
    """

    IDENTIFIED = "identified"
    ASSESSED = "assessed"
    TREATMENT_PLANNED = "treatment_planned"
    TREATMENT_IN_PROGRESS = "treatment_in_progress"
    MITIGATED = "mitigated"
    ACCEPTED = "accepted"
    TRANSFERRED = "transferred"
    AVOIDED = "avoided"
    REALISED = "realised"
    REJECTED = "rejected"
    CLOSED = "closed"


class TreatmentStrategy(str, enum.Enum):
    """How the risk is intended to be treated (ISO 31000's four responses).
    Distinct from `RiskStatus`: the strategy is the plan, the status is where
    the risk has got to."""

    MITIGATE = "mitigate"
    TRANSFER = "transfer"
    AVOID = "avoid"
    ACCEPT = "accept"
