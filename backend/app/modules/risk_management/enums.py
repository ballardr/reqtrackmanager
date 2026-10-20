"""
Module: modules.risk_management.enums

Risk Management's own vocabulary, kept in this package rather than core.
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


class TreatmentAssessmentStatus(str, enum.Enum):
    """A risk owner's verdict on whether one treatment link actually reduces
    the risk. A treatment link with no assessment row is
    implicitly `PROPOSED`; only `EFFECTIVE` counts toward the risk being treated.
    `NEEDS_REASSESSMENT` marks a verdict that may no longer hold."""

    PROPOSED = "proposed"
    EFFECTIVE = "effective"
    INEFFECTIVE = "ineffective"
    NEEDS_REASSESSMENT = "needs_reassessment"


class RiskReviewOutcome(str, enum.Enum):
    """What a periodic review concluded about a risk. `CONFIRMED` means
    the current assessment and treatment still stand; `REASSESSED` means the
    reviewer changed the assessment, treatment or status as part of the review
    (those edits are ordinary versions; the review records that they happened)."""

    CONFIRMED = "confirmed"
    REASSESSED = "reassessed"
