"""Provenance rows for custom report runs

Revision ID: 0108
Revises: 0107
Create Date: 2026-10-26

Adds `generated_reports`: one row per run of a report layout (layout and version, caller, UTC time, engine
version, format, parameters, scope, record counts and a digest of the records read). Guarded: a database
built from the current models already has the table.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0108"
down_revision: str | None = "0107"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS generated_reports (
            id UUID PRIMARY KEY,
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            project_id UUID REFERENCES projects(id) ON DELETE SET NULL,
            scope VARCHAR(20) NOT NULL,
            layout_id UUID NOT NULL,
            layout_name VARCHAR(200) NOT NULL,
            layout_version INTEGER NOT NULL,
            tree_hash VARCHAR(64) NOT NULL,
            requested_by UUID REFERENCES users(id) ON DELETE SET NULL,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL,
            format VARCHAR(10) NOT NULL,
            engine_version VARCHAR(20) NOT NULL,
            params JSONB NOT NULL,
            scope_project_ids JSONB NOT NULL,
            widgets JSONB NOT NULL,
            record_counts JSONB NOT NULL,
            stats JSONB NOT NULL,
            source_digest VARCHAR(64) NOT NULL
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_generated_reports_organization_id ON generated_reports (organization_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_generated_reports_project_id ON generated_reports (project_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_generated_reports_layout_id ON generated_reports (layout_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_generated_reports_created_at ON generated_reports (created_at)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS generated_reports")
