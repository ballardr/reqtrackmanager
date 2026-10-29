"""Folders an organisation or project added to its Reports picker

Revision ID: 0116
Revises: 0115
Create Date: 2026-10-29

Adds `report_folders`: one row per (scope, folder path), so a folder exists before any report is filed in it. Guarded: a
database built from the current models already has it.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0116"
down_revision: str | None = "0115"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS report_folders (
            id UUID PRIMARY KEY,
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
            path VARCHAR(120) NOT NULL,
            created_by UUID REFERENCES users(id) ON DELETE SET NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_report_folders_organization_id ON report_folders (organization_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_report_folders_project_id ON report_folders (project_id)")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_report_folders_org_path ON report_folders (organization_id, lower(path)) "
        "WHERE project_id IS NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_report_folders_project_path ON report_folders (project_id, lower(path)) "
        "WHERE project_id IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS report_folders")
