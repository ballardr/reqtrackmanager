"""
Module: modules.stakeholders.scoring

Stakeholders & Personas' registration into core's generic scoring-matrix
mechanism (`services.scoring`; Phase 0 resolution 16): the `stakeholder`
scheme, rating each Stakeholder on Influence and Interest, which drives the
power/interest grid and the suggested engagement cadence (`service.
suggest_cadence`).

Design decisions:
- One model, Influence × Interest, with three levels per axis (Low, Medium,
  High — the user-confirmed defaults; org-editable). The scheme's bands
  are a rough priority read-out, not the grid itself: the grid quadrant comes
  from each axis's level position (`service.grid_quadrant`).
- Org-level configuration is gated by the `stakeholder_type_admin` role (plus
  org admins), the same people who manage the Stakeholder type vocabulary
  (Decided by: Agent, mirroring Pain Points).
- Only a Stakeholder's *current* version references a level that the usage
  hooks manage; historic versions are cleared by the FK's `ON DELETE SET
  NULL`, so deleting a level never rewrites history (Decided by: Agent).
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.modules.registry import (
    ScoringAxisDefinition,
    ScoringBandDefault,
    ScoringLevelDefault,
    ScoringModelDefinition,
    ScoringSchemeDefinition,
)
from app.modules.stakeholders.models import StakeholderVersion

STAKEHOLDER_SCORING_SCHEME_KEY = "stakeholder"
INFLUENCE_AXIS_KEY = "influence"
INTEREST_AXIS_KEY = "interest"


def count_level_usage(db: Session, level_id: uuid.UUID) -> int:
    """How many *current* stakeholder versions reference `level_id` (see the
    module docstring for why history is excluded)."""
    return db.scalar(
        select(func.count(StakeholderVersion.id)).where(
            StakeholderVersion.valid_to.is_(None),
            (StakeholderVersion.influence_level_id == level_id) | (StakeholderVersion.interest_level_id == level_id),
        )
    ) or 0


def reassign_level_usage(db: Session, from_level_id: uuid.UUID, to_level_id: uuid.UUID) -> None:
    """Moves every current stakeholder version's reference from one level to
    another (the caller has checked both are on the same axis)."""
    for column in (StakeholderVersion.influence_level_id, StakeholderVersion.interest_level_id):
        db.execute(
            update(StakeholderVersion)
            .where(StakeholderVersion.valid_to.is_(None), column == from_level_id)
            .values({column.key: to_level_id})
        )


STAKEHOLDER_SCORING_SCHEME = ScoringSchemeDefinition(
    key=STAKEHOLDER_SCORING_SCHEME_KEY,
    label="Stakeholder scoring",
    axes=(
        ScoringAxisDefinition(
            key=INFLUENCE_AXIS_KEY, label="Influence",
            description="How much power the stakeholder has over the project's outcome.",
            default_levels=(
                ScoringLevelDefault("Low", 1, "Little ability to change the project's direction or outcome."),
                ScoringLevelDefault("Medium", 2, "Can shape parts of the project or block specific decisions."),
                ScoringLevelDefault("High", 3, "Can make or break the project."),
            ),
        ),
        ScoringAxisDefinition(
            key=INTEREST_AXIS_KEY, label="Interest",
            description="How much the project's outcome matters to the stakeholder.",
            default_levels=(
                ScoringLevelDefault("Low", 1, "Barely affected by the project."),
                ScoringLevelDefault("Medium", 2, "Affected in some areas."),
                ScoringLevelDefault("High", 3, "Directly and significantly affected."),
            ),
        ),
    ),
    models=(
        ScoringModelDefinition(
            key="influence_x_interest", label="Influence × Interest",
            axis_keys=(INFLUENCE_AXIS_KEY, INTEREST_AXIS_KEY),
            default_bands=(
                ScoringBandDefault("Low", 0.0, "muted"),
                ScoringBandDefault("Medium", 0.25, "info"),
                ScoringBandDefault("High", 0.6, "warning"),
            ),
        ),
    ),
    default_model_key="influence_x_interest",
    admin_role_key="stakeholder_type_admin",
    count_level_usage=count_level_usage,
    reassign_level_usage=reassign_level_usage,
)
