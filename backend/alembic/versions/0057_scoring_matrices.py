"""Generic scoring-matrix tables (Module 1 — Context & Strategy — Phase 10)

Revision ID: 0057
Revises: 0056
Create Date: 2026-10-04

Adds `scoring_levels`, `scoring_model_defaults` and `scoring_bands`
(`app.models.scoring`) — core, module-agnostic storage for the scoring
schemes modules register via `ModuleDefinition.scoring_schemes`.

No backfill here: levels come from the live registry, which a migration
can't read stably, so `app.services.scoring.sync_scoring_levels` seeds
every organisation's missing axes at each process start (and on org
creation). Model defaults and bands are override-only — no rows means
"inherit".
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0057"
down_revision: str | None = "0056"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Creates the three scoring tables and their indexes."""
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS scoring_levels (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            scheme_key VARCHAR(64) NOT NULL,
            axis_key VARCHAR(64) NOT NULL,
            name VARCHAR(100) NOT NULL,
            description TEXT,
            weight NUMERIC(10, 4) NOT NULL,
            CONSTRAINT uq_scoring_levels_name UNIQUE (organization_id, scheme_key, axis_key, name),
            CONSTRAINT uq_scoring_levels_weight UNIQUE (organization_id, scheme_key, axis_key, weight)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_scoring_levels_organization_id ON scoring_levels (organization_id)")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS scoring_model_defaults (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
            scheme_key VARCHAR(64) NOT NULL,
            model_key VARCHAR(64) NOT NULL
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_scoring_model_defaults_org "
        "ON scoring_model_defaults (organization_id, scheme_key) WHERE project_id IS NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_scoring_model_defaults_project "
        "ON scoring_model_defaults (project_id, scheme_key) WHERE project_id IS NOT NULL"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS scoring_bands (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
            scheme_key VARCHAR(64) NOT NULL,
            model_key VARCHAR(64) NOT NULL,
            label VARCHAR(100) NOT NULL,
            min_score NUMERIC(6, 4) NOT NULL,
            tone VARCHAR(20) NOT NULL,
            sort_order INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_scoring_bands_scope "
        "ON scoring_bands (organization_id, project_id, scheme_key, model_key)"
    )


def downgrade() -> None:
    """Drops the three scoring tables."""
    op.execute("DROP TABLE IF EXISTS scoring_bands")
    op.execute("DROP TABLE IF EXISTS scoring_model_defaults")
    op.execute("DROP TABLE IF EXISTS scoring_levels")
