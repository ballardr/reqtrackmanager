"""Project definition suppressions (hide an organisation default in one project)

Revision ID: 0101
Revises: 0100
Create Date: 2026-10-19

Adds `project_definition_suppressions`: one row per organisation default a project has
hidden, keyed by `(project, kind, organisation row)`. Seeds nothing, so every project keeps
seeing every organisation default until an admin hides one. Guarded: a database built from
the current models already has the table.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0101"
down_revision: str | None = "0100"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS project_definition_suppressions (
            project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            definition_kind VARCHAR(60) NOT NULL,
            org_definition_id UUID NOT NULL,
            PRIMARY KEY (project_id, definition_kind, org_definition_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_project_definition_suppressions_definition "
        "ON project_definition_suppressions (definition_kind, org_definition_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS project_definition_suppressions")
