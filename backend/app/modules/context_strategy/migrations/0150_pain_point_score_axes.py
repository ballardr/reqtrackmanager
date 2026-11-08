"""Pain Point scores, one row per axis

Revision ID: 0150
Revises: 0149
Create Date: 2026-11-08

Replaces the three level columns on `pain_point_scores` (severity, frequency, confidence) with
`pain_point_score_axes (score_id, axis_key, level_id)`, copying every existing level across first, so an axis
added later (Cost of Delay's, an organisation's own) needs no schema change. An "all personas" row keeps its
place and is now the General row; persona rows are unchanged. Deleting a level removes the rows that reference it.
Guarded so a database built from the current models passes.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0150"
down_revision: str | None = "0149"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_AXES = ("severity", "frequency", "confidence")


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS pain_point_score_axes (
            id UUID PRIMARY KEY,
            score_id UUID NOT NULL REFERENCES pain_point_scores(id) ON DELETE CASCADE,
            axis_key VARCHAR(64) NOT NULL,
            level_id UUID NOT NULL REFERENCES scoring_levels(id) ON DELETE CASCADE,
            CONSTRAINT uq_pain_point_score_axes_axis UNIQUE (score_id, axis_key)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_pain_point_score_axes_level ON pain_point_score_axes (level_id)")
    for axis in _AXES:
        op.execute(
            f"""
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'pain_point_scores' AND column_name = '{axis}_level_id'
                ) THEN
                    INSERT INTO pain_point_score_axes (id, score_id, axis_key, level_id)
                    SELECT gen_random_uuid(), id, '{axis}', {axis}_level_id
                    FROM pain_point_scores WHERE {axis}_level_id IS NOT NULL
                    ON CONFLICT DO NOTHING;
                END IF;
            END $$
            """
        )
        op.execute(f"ALTER TABLE pain_point_scores DROP COLUMN IF EXISTS {axis}_level_id")


def downgrade() -> None:
    for axis in _AXES:
        op.execute(
            f"ALTER TABLE pain_point_scores ADD COLUMN IF NOT EXISTS {axis}_level_id UUID "
            "REFERENCES scoring_levels(id)"
        )
        op.execute(
            f"UPDATE pain_point_scores p SET {axis}_level_id = a.level_id "
            "FROM pain_point_score_axes a "
            f"WHERE a.score_id = p.id AND a.axis_key = '{axis}'"
        )
    op.execute("DROP TABLE IF EXISTS pain_point_score_axes")
