"""Scoring: a project's own thresholds for a derived axis's levels

Revision ID: 0140
Revises: 0139
Create Date: 2026-11-06

Adds `scoring_level_thresholds`: a project may set its own threshold for each level of a derived axis (Demand),
so what "Many requesters" means can differ between projects. Guarded: a database built from the current models
already has it.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0140"
down_revision: str | None = "0139"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS scoring_level_thresholds (
            id UUID PRIMARY KEY,
            project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            level_id UUID NOT NULL REFERENCES scoring_levels(id) ON DELETE CASCADE,
            threshold NUMERIC(12, 4) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_scoring_level_thresholds_project_level UNIQUE (project_id, level_id),
            CONSTRAINT ck_scoring_level_thresholds_non_negative CHECK (threshold >= 0)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_scoring_level_thresholds_project_id ON scoring_level_thresholds (project_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_scoring_level_thresholds_level_id ON scoring_level_thresholds (level_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS scoring_level_thresholds")
