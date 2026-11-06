"""Enhancement request scoring levels, one row per axis

Revision ID: 0134
Revises: 0133
Create Date: 2026-11-05

Replaces the four level columns on `enhancement_request_versions` (reach, impact, confidence, effort) with
`enhancement_request_version_scores (version_id, axis_key, level_id)`, copying every existing level across first,
so a scheme axis added later (Ease, Demand, an organisation's own) needs no schema change. Deleting a level
removes the rows that reference it.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0134"
down_revision: str | None = "0133"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_AXES = ("reach", "impact", "confidence", "effort")


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS enhancement_request_version_scores (
            id UUID PRIMARY KEY,
            version_id UUID NOT NULL REFERENCES enhancement_request_versions(id) ON DELETE CASCADE,
            axis_key VARCHAR(64) NOT NULL,
            level_id UUID NOT NULL REFERENCES scoring_levels(id) ON DELETE CASCADE,
            CONSTRAINT uq_enhancement_request_version_scores_axis UNIQUE (version_id, axis_key)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_enhancement_request_version_scores_level "
        "ON enhancement_request_version_scores (level_id)"
    )
    for axis in _AXES:
        # Guarded: a database built from the current models has no such column to copy.
        op.execute(
            f"""
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'enhancement_request_versions' AND column_name = '{axis}_level_id'
                ) THEN
                    INSERT INTO enhancement_request_version_scores (id, version_id, axis_key, level_id)
                    SELECT gen_random_uuid(), id, '{axis}', {axis}_level_id
                    FROM enhancement_request_versions WHERE {axis}_level_id IS NOT NULL
                    ON CONFLICT DO NOTHING;
                END IF;
            END $$
            """
        )
        op.execute(f"ALTER TABLE enhancement_request_versions DROP COLUMN IF EXISTS {axis}_level_id")


def downgrade() -> None:
    for axis in _AXES:
        op.execute(
            f"ALTER TABLE enhancement_request_versions ADD COLUMN IF NOT EXISTS {axis}_level_id UUID "
            "REFERENCES scoring_levels(id) ON DELETE SET NULL"
        )
        op.execute(
            f"UPDATE enhancement_request_versions v SET {axis}_level_id = s.level_id "
            "FROM enhancement_request_version_scores s "
            f"WHERE s.version_id = v.id AND s.axis_key = '{axis}'"
        )
    op.execute("DROP TABLE IF EXISTS enhancement_request_version_scores")
