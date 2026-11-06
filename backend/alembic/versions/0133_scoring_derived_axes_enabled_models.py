"""Scoring: derived-axis level thresholds and per-tier enabled models

Revision ID: 0133
Revises: 0132
Create Date: 2026-11-05

Adds `scoring_levels.threshold` (the lowest derived value that falls in a level of a derived axis; null on an
ordinary axis) and `scoring_enabled_models` (the models a scheme offers at once, an organisation set and per-project
override sets). Guarded: a database built from the current models already has both.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0133"
down_revision: str | None = "0132"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE scoring_levels ADD COLUMN IF NOT EXISTS threshold NUMERIC(12, 4)")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS scoring_enabled_models (
            id UUID PRIMARY KEY,
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
            scheme_key VARCHAR(64) NOT NULL,
            model_key VARCHAR(64) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_scoring_enabled_models_org ON scoring_enabled_models "
        "(organization_id, scheme_key, model_key) WHERE project_id IS NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_scoring_enabled_models_project ON scoring_enabled_models "
        "(project_id, scheme_key, model_key) WHERE project_id IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS scoring_enabled_models")
    op.execute("ALTER TABLE scoring_levels DROP COLUMN IF EXISTS threshold")
