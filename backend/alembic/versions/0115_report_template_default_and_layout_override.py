"""Default report template and a layout's template override

Revision ID: 0115
Revises: 0114
Create Date: 2026-10-29

Adds `report_templates.is_default` (at most one per organisation, a partial unique index) and
`report_layouts.report_template_id` (the layout's own branding template; `NULL` falls back to the organisation's
default). Existing rows get no default and no override, so no report changes until an administrator sets one.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0115"
down_revision: str | None = "0114"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE report_templates ADD COLUMN IF NOT EXISTS is_default BOOLEAN NOT NULL DEFAULT false")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_report_templates_one_default ON report_templates (organization_id) WHERE is_default"
    )
    op.execute(
        "ALTER TABLE report_layouts ADD COLUMN IF NOT EXISTS report_template_id UUID "
        "CONSTRAINT fk_report_layouts_report_template_id REFERENCES report_templates(id) ON DELETE SET NULL"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE report_layouts DROP COLUMN IF EXISTS report_template_id")
    op.execute("DROP INDEX IF EXISTS uq_report_templates_one_default")
    op.execute("ALTER TABLE report_templates DROP COLUMN IF EXISTS is_default")
