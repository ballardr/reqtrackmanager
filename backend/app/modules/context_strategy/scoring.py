"""
Module: modules.context_strategy.scoring

Registers the `pain_point` scheme into core's scoring-matrix mechanism.
Per-persona axes: Severity, Frequency, Confidence, User/business value;
whole-Pain-Point axes (`per_target`): Time criticality, Risk reduction, Job
size. Models: `sxf`, `sxc`, `sxfxc` (default), `cod`, `wsjf`. Level-usage
hooks stop deleted levels orphaning scores.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.modules.context_strategy.models import PainPointScoreAxis
from app.modules.registry import (
    ScoringAxisDefinition,
    ScoringBandDefault,
    ScoringLevelDefault,
    ScoringModelDefinition,
    ScoringSchemeDefinition,
)

PAIN_POINT_SCORING_SCHEME_KEY = "pain_point"
PERSONA_TARGET_LABEL = "persona"
VALUE_AXIS_KEY = "value"
TIME_CRITICALITY_AXIS_KEY = "time_criticality"
RISK_REDUCTION_AXIS_KEY = "risk_reduction"
JOB_SIZE_AXIS_KEY = "job_size"

_RELATIVE_SCALE = (1, 2, 3, 5, 8, 13, 20)
#: The three Cost of Delay criteria carry equal importance (percentages total 100).
_EQUAL_THIRDS = (
    (VALUE_AXIS_KEY, 33.34), (TIME_CRITICALITY_AXIS_KEY, 33.33), (RISK_REDUCTION_AXIS_KEY, 33.33),
)


def count_level_usage(db: Session, level_id: uuid.UUID) -> int:
    """`ScoringSchemeDefinition.count_level_usage`: the number of Pain Point
    score rows referencing `level_id`."""
    return db.scalar(select(func.count(PainPointScoreAxis.id)).where(PainPointScoreAxis.level_id == level_id)) or 0


def reassign_level_usage(db: Session, from_level_id: uuid.UUID, to_level_id: uuid.UUID) -> None:
    """`ScoringSchemeDefinition.reassign_level_usage`: moves every Pain Point
    score reference from one level to another (same axis, checked by core)."""
    db.execute(
        update(PainPointScoreAxis).where(PainPointScoreAxis.level_id == from_level_id).values(level_id=to_level_id)
    )


def _bands(medium: float, high: float, critical: float) -> tuple[ScoringBandDefault, ...]:
    """Builds a Low/Medium/High/Critical band set from three normalised
    thresholds."""
    return (
        ScoringBandDefault("Low", 0.0, "muted"),
        ScoringBandDefault("Medium", medium, "info"),
        ScoringBandDefault("High", high, "warning"),
        ScoringBandDefault("Critical", critical, "danger"),
    )


def _relative_levels(names: tuple[str, ...]) -> tuple[ScoringLevelDefault, ...]:
    """Builds levels on the relative 1, 2, 3, 5, 8, 13, 20 scale, one per name, smallest first."""
    return tuple(ScoringLevelDefault(name, weight) for name, weight in zip(names, _RELATIVE_SCALE, strict=True))


PAIN_POINT_SCORING_SCHEME = ScoringSchemeDefinition(
    key=PAIN_POINT_SCORING_SCHEME_KEY,
    label="Pain Point scoring",
    axes=(
        ScoringAxisDefinition(
            key="severity", per_target=True, label="Severity",
            description="How badly the problem affects the persona (impact/consequence).",
            default_levels=(
                ScoringLevelDefault("Cosmetic", 1, "Noticeable, but the task is unaffected."),
                ScoringLevelDefault("Minor", 2, "Slows the persona down; an easy workaround exists."),
                ScoringLevelDefault("Moderate", 3, "Disrupts the task; the workaround is costly."),
                ScoringLevelDefault("Major", 4, "Seriously impairs the task; the workaround is hard or risky."),
                ScoringLevelDefault("Blocker", 5, "Unusable for this persona; no workaround."),
            ),
        ),
        ScoringAxisDefinition(
            key="frequency", per_target=True, label="Frequency",
            description="How often the persona hits the problem.",
            default_levels=(
                ScoringLevelDefault("Rare", 1, "A few times a year or less."),
                ScoringLevelDefault("Occasional", 2, "Roughly monthly."),
                ScoringLevelDefault("Frequent", 3, "Roughly weekly."),
                ScoringLevelDefault("Constant", 4, "Daily, or on every use."),
            ),
        ),
        ScoringAxisDefinition(
            key="confidence", per_target=True, label="Confidence",
            description="How sure we are of the severity and frequency.",
            default_levels=(
                ScoringLevelDefault("Low", 0.5, "Anecdotal or assumed."),
                ScoringLevelDefault("Medium", 0.8, "Some supporting evidence."),
                ScoringLevelDefault("High", 1, "Strong evidence, e.g. research or data."),
            ),
        ),
        ScoringAxisDefinition(
            key=VALUE_AXIS_KEY, label="User/business value", per_target=True,
            description="How much solving the problem is worth to the persona or the business.",
            default_levels=_relative_levels((
                "Minimal", "Low", "Moderate", "Substantial", "High", "Very high", "Exceptional",
            )),
        ),
        ScoringAxisDefinition(
            key=TIME_CRITICALITY_AXIS_KEY, label="Time criticality",
            description="How quickly the value decays: whether waiting costs more than a later delivery.",
            default_levels=_relative_levels((
                "No deadline", "Low", "Moderate", "Substantial", "High", "Very high", "Immediate",
            )),
        ),
        ScoringAxisDefinition(
            key=RISK_REDUCTION_AXIS_KEY, label="Risk reduction / opportunity enablement",
            description="How much solving the problem removes a risk or opens a later opportunity.",
            default_levels=_relative_levels((
                "None", "Low", "Moderate", "Substantial", "High", "Very high", "Exceptional",
            )),
        ),
        ScoringAxisDefinition(
            key=JOB_SIZE_AXIS_KEY, label="Job size",
            description="How large the work to solve the problem is. A larger job lowers the WSJF score.",
            default_levels=_relative_levels((
                "Tiny", "Small", "Moderate", "Medium", "Large", "Very large", "Epic",
            )),
        ),
    ),
    models=(
        ScoringModelDefinition(
            key="sxf", label="Severity × Frequency", axis_keys=("severity", "frequency"),
            default_bands=_bands(0.2, 0.4, 0.6),
        ),
        ScoringModelDefinition(
            key="sxc", label="Severity × Confidence", axis_keys=("severity", "confidence"),
            default_bands=_bands(0.3, 0.5, 0.8),
        ),
        ScoringModelDefinition(
            key="sxfxc", label="Severity × Frequency × Confidence", axis_keys=("severity", "frequency", "confidence"),
            default_bands=_bands(0.15, 0.3, 0.5),
        ),
        ScoringModelDefinition(
            key="cod", label="Cost of Delay (value + time criticality + risk reduction)",
            axis_keys=(VALUE_AXIS_KEY, TIME_CRITICALITY_AXIS_KEY, RISK_REDUCTION_AXIS_KEY),
            combination="weighted_sum", importance=_EQUAL_THIRDS, default_bands=_bands(0.3, 0.5, 0.75),
        ),
        ScoringModelDefinition(
            key="wsjf", label="WSJF (Cost of Delay ÷ job size)",
            axis_keys=(VALUE_AXIS_KEY, TIME_CRITICALITY_AXIS_KEY, RISK_REDUCTION_AXIS_KEY),
            divisor_axis_keys=(JOB_SIZE_AXIS_KEY,), combination="weighted_sum", importance=_EQUAL_THIRDS,
            default_bands=_bands(0.06, 0.15, 0.35),
        ),
    ),
    default_model_key="sxfxc",
    admin_role_key="pain_point_type_admin",
    allow_custom_criteria=True,
    side_by_side_models=True,
    target_label=PERSONA_TARGET_LABEL,
    count_level_usage=count_level_usage,
    reassign_level_usage=reassign_level_usage,
)
