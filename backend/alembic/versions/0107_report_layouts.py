"""Custom report layouts and their immutable versions

Revision ID: 0107
Revises: 0106
Create Date: 2026-10-26

Adds `report_layouts` (organisation- or project-level, `project_id` NULL for the organisation) and
`report_layout_versions` (one immutable tree per save). Guarded: a database built from the current
models already has both.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0107"
down_revision: str | None = "0106"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS report_layouts (
            id UUID PRIMARY KEY,
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
            name VARCHAR(200) NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            family VARCHAR(20) NOT NULL,
            current_version INTEGER NOT NULL DEFAULT 1,
            created_by UUID REFERENCES users(id) ON DELETE SET NULL,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL,
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_report_layouts_organization_id ON report_layouts (organization_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_report_layouts_project_id ON report_layouts (project_id)")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_report_layouts_org_name ON report_layouts (organization_id, name) "
        "WHERE project_id IS NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_report_layouts_project_name ON report_layouts (project_id, name) "
        "WHERE project_id IS NOT NULL"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS report_layout_versions (
            id UUID PRIMARY KEY,
            layout_id UUID NOT NULL REFERENCES report_layouts(id) ON DELETE CASCADE,
            version INTEGER NOT NULL,
            schema_version INTEGER NOT NULL,
            tree JSONB NOT NULL,
            tree_hash VARCHAR(64) NOT NULL,
            comment VARCHAR(500) NOT NULL DEFAULT '',
            created_by UUID REFERENCES users(id) ON DELETE SET NULL,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL,
            CONSTRAINT uq_report_layout_versions_layout_version UNIQUE (layout_id, version)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_report_layout_versions_layout_id ON report_layout_versions (layout_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS report_layout_versions")
    op.execute("DROP TABLE IF EXISTS report_layouts")
