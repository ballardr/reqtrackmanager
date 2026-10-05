"""Per-persona Pain Point scoring + intentional flag (Module 1 Phase 11)

Revision ID: 0064
Revises: 0063
Create Date: 2026-10-05

Adds `pain_points.is_intentional` and `pain_point_scores` (one
Severity/Frequency/Confidence rating of a Pain Point for one target, or for
"all personas" when the target is NULL — see `models.PainPointScore`).
No backfill: existing Pain Points are unscored and not intentional.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0064"
down_revision: str | None = "0063"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE pain_points ADD COLUMN IF NOT EXISTS is_intentional BOOLEAN NOT NULL DEFAULT false")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS pain_point_scores (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            pain_point_id UUID NOT NULL REFERENCES pain_points(id) ON DELETE CASCADE,
            target_type VARCHAR(64),
            target_id UUID,
            severity_level_id UUID REFERENCES scoring_levels(id),
            frequency_level_id UUID REFERENCES scoring_levels(id),
            confidence_level_id UUID REFERENCES scoring_levels(id),
            scored_by UUID REFERENCES users(id),
            CONSTRAINT ck_pain_point_scores_target_pair CHECK ((target_type IS NULL) = (target_id IS NULL))
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_pain_point_scores_pain_point_id ON pain_point_scores (pain_point_id)")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_pain_point_scores_all ON pain_point_scores (pain_point_id) "
        "WHERE target_id IS NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_pain_point_scores_target "
        "ON pain_point_scores (pain_point_id, target_type, target_id) WHERE target_id IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS pain_point_scores")
    op.execute("ALTER TABLE pain_points DROP COLUMN IF EXISTS is_intentional")
