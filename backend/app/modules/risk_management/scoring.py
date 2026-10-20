"""
Module: modules.risk_management.scoring

Risk Management's registration into core's generic scoring-matrix mechanism:
the `risk` scheme with Likelihood, Consequence
and Detectability axes and two models, Likelihood × Consequence (the default)
and Likelihood × Consequence × Detectability (FMEA-style).

Design decisions (all **Decided by: Agent** except the reuse itself, which is
**Decided by: User**):
- Detectability weights run the FMEA way: a *higher* weight means the problem
  is *harder* to detect, so a higher product is always a worse risk.
- The top Consequence level is "Catastrophic", the top Likelihood level
  "Almost certain".
- Default bands are per model, because a three-axis product sits lower on the
  normalised scale than a two-axis one. The two-axis thresholds reproduce the
  common 5x5 reading (product 1-4 Low, 5-9 Medium, 10-16 High, 20+ Critical);
  a matrix that is not monotonic in the product is expressed with core's
  per-cell rating override, not here.
- Org-level configuration is gated by the `risk_type_admin` role (plus org
  admins), the same people who manage the Risk type vocabulary.
- `count_level_usage`/`reassign_level_usage` act on *current* risk versions
  only, so deleting an in-use level forces a reassignment while history keeps
  its (then null) reference.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from app.modules.registry import (
    ScoringAxisDefinition,
    ScoringBandDefault,
    ScoringLevelDefault,
    ScoringModelDefinition,
    ScoringSchemeDefinition,
)
from app.modules.risk_management.models import RiskVersion

RISK_SCORING_SCHEME_KEY = "risk"
LIKELIHOOD_AXIS_KEY = "likelihood"
CONSEQUENCE_AXIS_KEY = "consequence"
DETECTABILITY_AXIS_KEY = "detectability"

# RiskVersion column -> the scheme axis its level must belong to, inherent first.
LEVEL_COLUMN_AXES: dict[str, str] = {
    "inherent_likelihood_level_id": LIKELIHOOD_AXIS_KEY,
    "inherent_consequence_level_id": CONSEQUENCE_AXIS_KEY,
    "inherent_detectability_level_id": DETECTABILITY_AXIS_KEY,
    "residual_likelihood_level_id": LIKELIHOOD_AXIS_KEY,
    "residual_consequence_level_id": CONSEQUENCE_AXIS_KEY,
    "residual_detectability_level_id": DETECTABILITY_AXIS_KEY,
}


def count_level_usage(db: Session, level_id: uuid.UUID) -> int:
    """`ScoringSchemeDefinition.count_level_usage`: how many *current* risk
    versions reference `level_id` on any axis."""
    clause = or_(*(getattr(RiskVersion, column) == level_id for column in LEVEL_COLUMN_AXES))
    return db.scalar(select(func.count(RiskVersion.id)).where(RiskVersion.valid_to.is_(None), clause)) or 0


def reassign_level_usage(db: Session, from_level_id: uuid.UUID, to_level_id: uuid.UUID) -> None:
    """`ScoringSchemeDefinition.reassign_level_usage`: moves every current risk
    version's reference from one level to another (core has checked both are on
    the same axis)."""
    for column in LEVEL_COLUMN_AXES:
        attribute = getattr(RiskVersion, column)
        db.execute(
            update(RiskVersion).where(RiskVersion.valid_to.is_(None), attribute == from_level_id).values({column: to_level_id})
        )


def _bands(medium: float, high: float, critical: float) -> tuple[ScoringBandDefault, ...]:
    """Builds a Low/Medium/High/Critical band set from three normalised thresholds."""
    return (
        ScoringBandDefault("Low", 0.0, "muted"),
        ScoringBandDefault("Medium", medium, "info"),
        ScoringBandDefault("High", high, "warning"),
        ScoringBandDefault("Critical", critical, "danger"),
    )


RISK_SCORING_SCHEME = ScoringSchemeDefinition(
    key=RISK_SCORING_SCHEME_KEY,
    label="Risk scoring",
    axes=(
        ScoringAxisDefinition(
            key=LIKELIHOOD_AXIS_KEY, label="Likelihood", description="How likely the risk event is to occur.",
            default_levels=(
                ScoringLevelDefault("Rare", 1, "Not expected to occur; under about 5%."),
                ScoringLevelDefault("Unlikely", 2, "Could occur, but not expected; about 5-20%."),
                ScoringLevelDefault("Possible", 3, "Might occur; about 20-50%."),
                ScoringLevelDefault("Likely", 4, "Will probably occur; about 50-80%."),
                ScoringLevelDefault("Almost certain", 5, "Expected to occur; over about 80%."),
            ),
        ),
        ScoringAxisDefinition(
            key=CONSEQUENCE_AXIS_KEY, label="Consequence",
            description="How severe the effect is if the risk event occurs (safety, cost, schedule, quality).",
            default_levels=(
                ScoringLevelDefault("Insignificant", 1, "Negligible effect; absorbed within normal work."),
                ScoringLevelDefault("Minor", 2, "Small effect; recoverable with minor rework."),
                ScoringLevelDefault("Moderate", 3, "Noticeable effect on cost, schedule or quality."),
                ScoringLevelDefault("Major", 4, "Serious effect; objectives are at risk."),
                ScoringLevelDefault("Catastrophic", 5, "Severe effect; harm, or failure of the project's objectives."),
            ),
        ),
        ScoringAxisDefinition(
            key=DETECTABILITY_AXIS_KEY, label="Detectability",
            description="How well the problem would be noticed before it causes its effect (a higher weight is harder to detect).",
            default_levels=(
                ScoringLevelDefault("Detected immediately", 1, "Certain to be seen as it happens."),
                ScoringLevelDefault("Detected early", 2, "Very likely to be seen in time to act."),
                ScoringLevelDefault("Detected before impact", 3, "Likely to be seen, but with little time to act."),
                ScoringLevelDefault("Detected late", 4, "Probably only seen once the effect has begun."),
                ScoringLevelDefault("Undetectable", 5, "No reliable way to notice it before the effect."),
            ),
        ),
    ),
    models=(
        ScoringModelDefinition(
            key="lxc", label="Likelihood × Consequence", axis_keys=(LIKELIHOOD_AXIS_KEY, CONSEQUENCE_AXIS_KEY),
            default_bands=_bands(0.2, 0.4, 0.7),
        ),
        ScoringModelDefinition(
            key="lxcxd", label="Likelihood × Consequence × Detectability",
            axis_keys=(LIKELIHOOD_AXIS_KEY, CONSEQUENCE_AXIS_KEY, DETECTABILITY_AXIS_KEY),
            default_bands=_bands(0.08, 0.2, 0.4),
        ),
    ),
    default_model_key="lxc",
    admin_role_key="risk_type_admin",
    count_level_usage=count_level_usage,
    reassign_level_usage=reassign_level_usage,
)
