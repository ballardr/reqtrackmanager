"""A folder for report layouts and packs, and report placements

Revision ID: 0113
Revises: 0112
Create Date: 2026-10-28

Adds `folder` (the path the Reports picker files the row under; empty = the picker's default folder) to
`report_layouts` and `report_packs`, and `report_placements` (an organisation's or project's override of where a report
appears and whether it is shown). Guarded: a database built from the current models already has all of it.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0113"
down_revision: str | None = "0112"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for table in ("report_layouts", "report_packs"):
        op.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS folder VARCHAR(120) NOT NULL DEFAULT ''")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS report_placements (
            id UUID PRIMARY KEY,
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
            report_key VARCHAR(120) NOT NULL,
            folder VARCHAR(120),
            hidden BOOLEAN,
            updated_by UUID REFERENCES users(id) ON DELETE SET NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_report_placements_organization_id ON report_placements (organization_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_report_placements_project_id ON report_placements (project_id)")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_report_placements_org_key ON report_placements (organization_id, report_key) "
        "WHERE project_id IS NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_report_placements_project_key ON report_placements (project_id, report_key) "
        "WHERE project_id IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS report_placements")
    for table in ("report_layouts", "report_packs"):
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS folder")
