"""Requirement aliases: `requirement_aliases`, the alias setting columns and `artefact_links.note`.

Revision ID: 0206
Revises: 0205
Create Date: 2026-11-21

A requirement can sit in further components and categories, each with a code of its own. Nothing is backfilled: every
existing requirement has no alias, every organisation reads `allowed` and every project inherits. Guarded so a
database built from the current models passes.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0206"
down_revision: str | None = "0205"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS requirement_aliases (
            id UUID PRIMARY KEY,
            project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            requirement_id UUID NOT NULL REFERENCES requirements(id) ON DELETE CASCADE,
            component_id UUID REFERENCES project_components(id) ON DELETE SET NULL,
            category_id UUID REFERENCES project_categories(id) ON DELETE SET NULL,
            unique_code VARCHAR(64) NOT NULL,
            is_retired BOOLEAN NOT NULL DEFAULT false,
            retired_at TIMESTAMPTZ,
            created_by UUID REFERENCES users(id) ON DELETE SET NULL,
            created_at TIMESTAMPTZ NOT NULL,
            CONSTRAINT uq_requirement_aliases_code UNIQUE (project_id, unique_code)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_requirement_aliases_requirement ON requirement_aliases (requirement_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_requirement_aliases_project ON requirement_aliases (project_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_requirement_aliases_component ON requirement_aliases (component_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_requirement_aliases_category ON requirement_aliases (category_id)")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_requirement_aliases_active_pair "
        "ON requirement_aliases (requirement_id, component_id, category_id) WHERE is_retired IS FALSE"
    )
    op.execute("ALTER TABLE organizations ADD COLUMN IF NOT EXISTS requirement_aliases VARCHAR(10) NOT NULL DEFAULT 'allowed'")
    op.execute("ALTER TABLE projects ADD COLUMN IF NOT EXISTS requirement_aliases VARCHAR(10)")
    op.execute("ALTER TABLE artefact_links ADD COLUMN IF NOT EXISTS note VARCHAR(200)")


def downgrade() -> None:
    op.execute("ALTER TABLE artefact_links DROP COLUMN IF EXISTS note")
    op.execute("ALTER TABLE projects DROP COLUMN IF EXISTS requirement_aliases")
    op.execute("ALTER TABLE organizations DROP COLUMN IF EXISTS requirement_aliases")
    op.execute("DROP TABLE IF EXISTS requirement_aliases")
