"""Report chapter-layout toggle and per-project default report template

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-10

Adds `ReportTemplate.chapters_per_component` (whether a PDF report chapters
by component or renders continuously — see `services/reports.py`) and
`Project.default_report_template_id` (pre-selected on the report generation
page, see `docs/decisions.md`'s "PDF reports: intro/template defaults,
continuous-layout toggle" entry).

`IF NOT EXISTS`/`IF EXISTS` throughout for the same reason 0002 uses it: on
a brand-new database, 0001's `create_all()` already creates these columns
against the current model classes, so a plain `ADD COLUMN` would fail there
with "already exists"; on an already-migrated database from before this
revision, they're genuinely missing. `IF NOT EXISTS` converges to the same
end state either way.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE report_templates ADD COLUMN IF NOT EXISTS chapters_per_component BOOLEAN NOT NULL DEFAULT true"
    )
    op.execute(
        "ALTER TABLE projects ADD COLUMN IF NOT EXISTS default_report_template_id UUID "
        "REFERENCES report_templates(id) ON DELETE SET NULL"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE projects DROP COLUMN IF EXISTS default_report_template_id")
    op.execute("ALTER TABLE report_templates DROP COLUMN IF EXISTS chapters_per_component")
