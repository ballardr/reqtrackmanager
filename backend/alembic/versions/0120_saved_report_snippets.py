"""Author-saved report snippets: report_snippets

Revision ID: 0120
Revises: 0119
Create Date: 2026-10-30

Adds `report_snippets` (organisation- or project-level, `project_id` NULL for the organisation): a named fragment of a
layout (blocks plus the page styles and variables they use). Guarded: a database built from the current models already
has it.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0120"
down_revision: str | None = "0119"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS report_snippets (
            id UUID PRIMARY KEY,
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
            name VARCHAR(200) NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            category VARCHAR(60) NOT NULL,
            family VARCHAR(20) NOT NULL,
            blocks JSONB NOT NULL,
            root JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_by UUID REFERENCES users(id) ON DELETE SET NULL,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL,
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_report_snippets_organization_id ON report_snippets (organization_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_report_snippets_project_id ON report_snippets (project_id)")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_report_snippets_org_name ON report_snippets (organization_id, name) "
        "WHERE project_id IS NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_report_snippets_project_name ON report_snippets (project_id, name) "
        "WHERE project_id IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS report_snippets")
