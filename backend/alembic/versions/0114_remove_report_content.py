"""Remove report content and the project default report template

Revision ID: 0114
Revises: 0113
Create Date: 2026-10-28

Drops `report_contents` (the introductions, chapters and appendices a template, project or organisation held per
report; authored text now lives in report layouts) and `projects.default_report_template_id`. The data is not
converted: the rows are deleted. `downgrade` recreates the empty table and column, not the data.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0114"
down_revision: str | None = "0113"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("DROP TABLE IF EXISTS report_contents")
    op.execute("ALTER TABLE projects DROP COLUMN IF EXISTS default_report_template_id")


def downgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS report_contents (
            id UUID PRIMARY KEY,
            scope_type VARCHAR(20) NOT NULL,
            scope_id UUID NOT NULL,
            report_key VARCHAR(100) NOT NULL,
            intro TEXT NOT NULL DEFAULT '',
            chapters JSONB NOT NULL DEFAULT '[]'::jsonb,
            appendices JSONB NOT NULL DEFAULT '[]'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_report_contents_scope_key UNIQUE (scope_type, scope_id, report_key)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_report_contents_scope_id ON report_contents (scope_id)")
    op.execute(
        "ALTER TABLE projects ADD COLUMN IF NOT EXISTS default_report_template_id UUID "
        "REFERENCES report_templates(id) ON DELETE SET NULL"
    )
