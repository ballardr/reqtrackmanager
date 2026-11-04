"""Scoring: organisation- and project-defined axes and models, hidden registered criteria

Revision ID: 0135
Revises: 0134
Create Date: 2026-11-05

Adds `scoring_custom_axes`, `scoring_custom_models` and `scoring_hidden_criteria`, and `scoring_levels.project_id`
(the project that owns a project-defined axis's levels, which then go with the project). Guarded: a database built
from the current models already has them.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0135"
down_revision: str | None = "0134"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE scoring_levels ADD COLUMN IF NOT EXISTS project_id UUID REFERENCES projects(id) ON DELETE CASCADE"
    )
    for table, extra in (
        ("scoring_custom_axes", "description TEXT"),
        ("scoring_custom_models", "definition JSONB NOT NULL"),
    ):
        op.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {table} (
                id UUID PRIMARY KEY,
                organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
                project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
                scheme_key VARCHAR(64) NOT NULL,
                key VARCHAR(64) NOT NULL,
                label VARCHAR(100) NOT NULL,
                {extra},
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                CONSTRAINT uq_{table}_key UNIQUE (organization_id, scheme_key, key)
            )
            """
        )
        op.execute(f"CREATE INDEX IF NOT EXISTS ix_{table}_organization_id ON {table} (organization_id)")
        op.execute(f"CREATE INDEX IF NOT EXISTS ix_{table}_project_id ON {table} (project_id)")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS scoring_hidden_criteria (
            id UUID PRIMARY KEY,
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            scheme_key VARCHAR(64) NOT NULL,
            kind VARCHAR(10) NOT NULL,
            key VARCHAR(64) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_scoring_hidden_criteria UNIQUE (organization_id, scheme_key, kind, key)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_scoring_hidden_criteria_organization_id ON scoring_hidden_criteria (organization_id)")


def downgrade() -> None:
    for table in ("scoring_hidden_criteria", "scoring_custom_models", "scoring_custom_axes"):
        op.execute(f"DROP TABLE IF EXISTS {table}")
    op.execute("ALTER TABLE scoring_levels DROP COLUMN IF EXISTS project_id")
