"""
Module: modules.product_feedback.scoring

Registers the `enhancement_request` scheme into core's scoring-matrix
mechanism: axes Reach, Impact, Confidence, Ease, Effort, Demand; models `ice`,
`rice` (default) and `rice_demand`. Effort is a divisor axis; Demand is derived
from weighted demand (a manual level wins); Reach stays manual. Levels are
organisation-wide; configuration needs `org_feedback_triager`. Custom criteria
resolve through `services.scoring_custom.effective_scheme`.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Select, func, select, update
from sqlalchemy.orm import Session

from app.modules.product_feedback.models import EnhancementRequestVersion, EnhancementRequestVersionScore
from app.modules.registry import (
    ScoringAxisDefinition,
    ScoringBandDefault,
    ScoringLevelDefault,
    ScoringModelDefinition,
    ScoringSchemeDefinition,
)

REQUEST_SCORING_SCHEME_KEY = "enhancement_request"
REACH_AXIS_KEY = "reach"
IMPACT_AXIS_KEY = "impact"
CONFIDENCE_AXIS_KEY = "confidence"
EASE_AXIS_KEY = "ease"
EFFORT_AXIS_KEY = "effort"
DEMAND_AXIS_KEY = "demand"

#: `ScoringAxisDefinition.derived_source` of the Demand axis: the request's weighted demand (`demand.py`).
WEIGHTED_DEMAND_SOURCE = "weighted_demand"


def _current_version_ids() -> Select:
    """The ids of every request's current version."""
    return select(EnhancementRequestVersion.id).where(EnhancementRequestVersion.valid_to.is_(None))


def count_level_usage(db: Session, level_id: uuid.UUID) -> int:
    """`ScoringSchemeDefinition.count_level_usage`: how many *current* request versions reference `level_id`."""
    return db.scalar(
        select(func.count(EnhancementRequestVersionScore.id)).where(
            EnhancementRequestVersionScore.level_id == level_id,
            EnhancementRequestVersionScore.version_id.in_(_current_version_ids()),
        )
    ) or 0


def reassign_level_usage(db: Session, from_level_id: uuid.UUID, to_level_id: uuid.UUID) -> None:
    """`ScoringSchemeDefinition.reassign_level_usage`: moves every current request version's reference from one
    level to another (core has checked both are on the same axis)."""
    db.execute(
        update(EnhancementRequestVersionScore)
        .where(
            EnhancementRequestVersionScore.level_id == from_level_id,
            EnhancementRequestVersionScore.version_id.in_(_current_version_ids()),
        )
        .values(level_id=to_level_id)
    )


def _bands(medium: float, high: float) -> tuple[ScoringBandDefault, ...]:
    """Builds a Low/Medium/High band set from two normalised thresholds."""
    return (
        ScoringBandDefault("Low", 0.0, "muted"),
        ScoringBandDefault("Medium", medium, "info"),
        ScoringBandDefault("High", high, "accent"),
    )


REQUEST_SCORING_SCHEME = ScoringSchemeDefinition(
    key=REQUEST_SCORING_SCHEME_KEY,
    label="Enhancement request scoring",
    axes=(
        ScoringAxisDefinition(
            key=REACH_AXIS_KEY, label="Reach", description="How many of the people affected would use or notice it.",
            default_levels=(
                ScoringLevelDefault("Few", 1, "A handful of people or one small team."),
                ScoringLevelDefault("Some", 2, "One group or a minority of users."),
                ScoringLevelDefault("Many", 3, "Several groups or about half of users."),
                ScoringLevelDefault("Most", 4, "Most users."),
                ScoringLevelDefault("Everyone", 5, "Effectively every user."),
            ),
        ),
        ScoringAxisDefinition(
            key=IMPACT_AXIS_KEY, label="Impact", description="How much it improves things for each person reached.",
            default_levels=(
                ScoringLevelDefault("Minimal", 0.25, "A small convenience."),
                ScoringLevelDefault("Low", 0.5, "A noticeable but minor improvement."),
                ScoringLevelDefault("Medium", 1, "A clear improvement to the task."),
                ScoringLevelDefault("High", 2, "Removes a major obstacle."),
                ScoringLevelDefault("Massive", 3, "Changes what the person can do."),
            ),
        ),
        ScoringAxisDefinition(
            key=CONFIDENCE_AXIS_KEY, label="Confidence", description="How sure we are of the reach and impact.",
            default_levels=(
                ScoringLevelDefault("Low", 0.5, "A guess or a single anecdote."),
                ScoringLevelDefault("Medium", 0.8, "Some supporting evidence."),
                ScoringLevelDefault("High", 1, "Strong evidence, e.g. research or data."),
            ),
        ),
        ScoringAxisDefinition(
            key=EASE_AXIS_KEY, label="Ease",
            description="How easy it is to deliver. A higher level raises the score.",
            default_levels=(
                ScoringLevelDefault("Very hard", 1, "More than a quarter of work, or a major unknown."),
                ScoringLevelDefault("Hard", 2, "A quarter."),
                ScoringLevelDefault("Moderate", 3, "A few weeks."),
                ScoringLevelDefault("Easy", 4, "Up to about a week."),
                ScoringLevelDefault("Very easy", 5, "A day or two."),
            ),
        ),
        ScoringAxisDefinition(
            key=EFFORT_AXIS_KEY, label="Effort",
            description="How much work it takes to deliver. A higher level lowers the score.",
            default_levels=(
                ScoringLevelDefault("Trivial", 0.5, "A day or two."),
                ScoringLevelDefault("Small", 1, "Up to about a week."),
                ScoringLevelDefault("Medium", 2, "A few weeks."),
                ScoringLevelDefault("Large", 4, "A quarter."),
                ScoringLevelDefault("Huge", 8, "More than a quarter."),
            ),
        ),
        ScoringAxisDefinition(
            key=DEMAND_AXIS_KEY, label="Demand",
            description="How much weighted demand stands behind it, derived from its requesters. A level can be "
            "chosen manually to override the derived one.",
            derived_source=WEIGHTED_DEMAND_SOURCE,
            default_levels=(
                ScoringLevelDefault("Single voice", 1, "Up to a couple of requesters.", threshold=0),
                ScoringLevelDefault("A few", 2, "A handful of requesters.", threshold=3),
                ScoringLevelDefault("Several", 3, "A sizeable group of requesters.", threshold=8),
                ScoringLevelDefault("Many", 4, "Many requesters, or very influential ones.", threshold=15),
                ScoringLevelDefault("Widespread", 5, "Demand across most of the people involved.", threshold=30),
            ),
        ),
    ),
    models=(
        ScoringModelDefinition(
            key="ice", label="ICE (Impact × Confidence × Ease)",
            axis_keys=(IMPACT_AXIS_KEY, CONFIDENCE_AXIS_KEY, EASE_AXIS_KEY), default_bands=_bands(0.15, 0.4),
        ),
        ScoringModelDefinition(
            key="rice", label="RICE (Reach × Impact × Confidence ÷ Effort)",
            axis_keys=(REACH_AXIS_KEY, IMPACT_AXIS_KEY, CONFIDENCE_AXIS_KEY), divisor_axis_keys=(EFFORT_AXIS_KEY,),
            default_bands=_bands(0.03, 0.1),
        ),
        ScoringModelDefinition(
            key="rice_demand", label="RICE with derived demand (Demand × Impact × Confidence ÷ Effort)",
            axis_keys=(DEMAND_AXIS_KEY, IMPACT_AXIS_KEY, CONFIDENCE_AXIS_KEY), divisor_axis_keys=(EFFORT_AXIS_KEY,),
            default_bands=_bands(0.03, 0.1),
        ),
    ),
    default_model_key="rice",
    admin_role_key="org_feedback_triager",
    allow_custom_criteria=True,
    side_by_side_models=True,
    count_level_usage=count_level_usage,
    reassign_level_usage=reassign_level_usage,
)
