"""A project can set a short report name: projects.report_name

Revision ID: 0128
Revises: 0127
Create Date: 2026-11-03

Adds `projects.report_name` (nullable text, 255 characters at most): a short display name reports may print in headers,
footers and titles through `{{project_report_name}}`. Guarded: a database built from the current models already has it.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0128"
down_revision: str | None = "0127"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE projects ADD COLUMN IF NOT EXISTS report_name VARCHAR(255)")


def downgrade() -> None:
    op.execute("ALTER TABLE projects DROP COLUMN IF EXISTS report_name")
