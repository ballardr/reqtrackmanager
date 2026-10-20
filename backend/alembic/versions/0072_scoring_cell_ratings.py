"""Per-cell scoring rating overrides (Risk Management)

Revision ID: 0072
Revises: 0071
Create Date: 2026-10-12

Adds `scoring_cell_ratings` (`app.models.scoring.ScoringCellRating`): an
explicit (axis-1 level, axis-2 level) -> band label mapping for a two-axis
scoring model, at org level (`project_id` NULL) or as a project override.
Override-only like `scoring_bands`: no rows means "inherit", so there is
nothing to backfill and existing schemes keep their threshold bands.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0072"
down_revision: str | None = "0071"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Creates the table and its two scope-uniqueness indexes."""
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS scoring_cell_ratings (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
            scheme_key VARCHAR(64) NOT NULL,
            model_key VARCHAR(64) NOT NULL,
            first_level_id UUID NOT NULL REFERENCES scoring_levels(id) ON DELETE CASCADE,
            second_level_id UUID NOT NULL REFERENCES scoring_levels(id) ON DELETE CASCADE,
            band_label VARCHAR(100) NOT NULL
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_scoring_cell_ratings_organization_id ON scoring_cell_ratings (organization_id)")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_scoring_cell_ratings_org "
        "ON scoring_cell_ratings (organization_id, scheme_key, model_key, first_level_id, second_level_id) "
        "WHERE project_id IS NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_scoring_cell_ratings_project "
        "ON scoring_cell_ratings (project_id, scheme_key, model_key, first_level_id, second_level_id) "
        "WHERE project_id IS NOT NULL"
    )


def downgrade() -> None:
    """Drops the table."""
    op.execute("DROP TABLE IF EXISTS scoring_cell_ratings")
