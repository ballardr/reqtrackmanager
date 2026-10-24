"""Record export/import personal-data policy

Revision ID: 0105
Revises: 0104
Create Date: 2026-10-23

Adds `server_record_sensitivity_defaults` and `organization_record_sensitivity_overrides`: the
explicit-override-only allow/deny decision per sensitivity tag, at server and organisation level.
Seeds nothing, so every tag stays excluded until an administrator opts in. Guarded: a database
built from the current models already has the tables.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0105"
down_revision: str | None = "0104"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS server_record_sensitivity_defaults (
            tag VARCHAR(40) PRIMARY KEY,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            allowed BOOLEAN NOT NULL,
            updated_by UUID REFERENCES users(id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS organization_record_sensitivity_overrides (
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            tag VARCHAR(40) NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            allowed BOOLEAN NOT NULL,
            updated_by UUID REFERENCES users(id),
            PRIMARY KEY (organization_id, tag)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS organization_record_sensitivity_overrides")
    op.execute("DROP TABLE IF EXISTS server_record_sensitivity_defaults")
