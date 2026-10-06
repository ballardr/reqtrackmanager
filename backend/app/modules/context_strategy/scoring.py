"""
Module: modules.context_strategy.scoring

Context & Strategy's registration into core's generic scoring-matrix
mechanism (Module 1 Phase 10; design from Phase 9): the `pain_point`
scheme, scored per persona (Phase 11) on Severity, Frequency and
Confidence, combined by one of three models chosen when viewing.

Design decisions:
- Severity is the same input as Impact/consequence (Phase 9 Q2, Decided by:
  User); its top level is "Blocker", which Phase 11's Blocker badge keys off
  (top level = highest weight, see `services.scoring`).
- Confidence uses fractional weights (0.5/0.8/1.0), so it discounts a score
  rather than inflating it, RICE-style (Decided by: Agent; org-editable).
- System default model S×F×C (Phase 9 Q3, Decided by: Agent). Default bands
  are per model because a three-axis product sits lower on the normalised
  scale than a two-axis one (Decided by: Agent).
- Org-level configuration is gated by the existing `pain_point_type_admin`
  role (plus org admins) — the same people who manage the Pain Point type
  vocabulary (Decided by: Agent).
- `count_level_usage`/`reassign_level_usage` count and move `PainPointScore`
  references (Phase 11), so deleting an in-use level forces a reassignment
  instead of leaving a score pointing at nothing.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from app.modules.context_strategy.models import PainPointScore
from app.modules.registry import (
    ScoringAxisDefinition,
    ScoringBandDefault,
    ScoringLevelDefault,
    ScoringModelDefinition,
    ScoringSchemeDefinition,
)

PAIN_POINT_SCORING_SCHEME_KEY = "pain_point"
_LEVEL_COLUMNS = ("severity_level_id", "frequency_level_id", "confidence_level_id")


def count_level_usage(db: Session, level_id: uuid.UUID) -> int:
    """`ScoringSchemeDefinition.count_level_usage`: the number of Pain Point
    score rows referencing `level_id` on any axis."""
    clause = or_(*(getattr(PainPointScore, c) == level_id for c in _LEVEL_COLUMNS))
    return db.scalar(select(func.count(PainPointScore.id)).where(clause)) or 0


def reassign_level_usage(db: Session, from_level_id: uuid.UUID, to_level_id: uuid.UUID) -> None:
    """`ScoringSchemeDefinition.reassign_level_usage`: moves every Pain Point
    score reference from one level to another (same axis, checked by core)."""
    for column in _LEVEL_COLUMNS:
        db.execute(
            update(PainPointScore).where(getattr(PainPointScore, column) == from_level_id)
            .values({column: to_level_id})
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


PAIN_POINT_SCORING_SCHEME = ScoringSchemeDefinition(
    key=PAIN_POINT_SCORING_SCHEME_KEY,
    label="Pain Point scoring",
    axes=(
        ScoringAxisDefinition(
            key="severity", label="Severity",
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
            key="frequency", label="Frequency",
            description="How often the persona hits the problem.",
            default_levels=(
                ScoringLevelDefault("Rare", 1, "A few times a year or less."),
                ScoringLevelDefault("Occasional", 2, "Roughly monthly."),
                ScoringLevelDefault("Frequent", 3, "Roughly weekly."),
                ScoringLevelDefault("Constant", 4, "Daily, or on every use."),
            ),
        ),
        ScoringAxisDefinition(
            key="confidence", label="Confidence",
            description="How sure we are of the severity and frequency.",
            default_levels=(
                ScoringLevelDefault("Low", 0.5, "Anecdotal or assumed."),
                ScoringLevelDefault("Medium", 0.8, "Some supporting evidence."),
                ScoringLevelDefault("High", 1, "Strong evidence, e.g. research or data."),
            ),
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
    ),
    default_model_key="sxfxc",
    admin_role_key="pain_point_type_admin",
    count_level_usage=count_level_usage,
    reassign_level_usage=reassign_level_usage,
)
