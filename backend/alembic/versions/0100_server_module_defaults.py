"""Server-wide default module states

Revision ID: 0100
Revises: 0099
Create Date: 2026-10-19

Adds `server_module_defaults`: an explicit-override-only table of the server-wide default
for each module (enabled for an organisation with no row of its own, and on by default for
its projects). Seeds nothing, so an upgraded deployment keeps its current effective states;
a fresh install is seeded at first start by the application. Guarded: a database built from
the current models already has the table.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0100"
down_revision: str | None = "0099"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS server_module_defaults (
            id UUID PRIMARY KEY,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            module_key VARCHAR(100) NOT NULL,
            org_enabled BOOLEAN NOT NULL,
            project_default_enabled BOOLEAN NOT NULL,
            updated_by UUID REFERENCES users(id),
            CONSTRAINT uq_server_module_defaults_module_key UNIQUE (module_key)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS server_module_defaults")
