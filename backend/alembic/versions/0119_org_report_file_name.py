"""An organisation can set a default report file name: organizations.report_file_name

Revision ID: 0119
Revises: 0118
Create Date: 2026-10-30

Adds `organizations.report_file_name` (nullable text, a `{{placeholder}}` template without extension). Guarded: a
database built from the current models already has it.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0119"
down_revision: str | None = "0118"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE organizations ADD COLUMN IF NOT EXISTS report_file_name VARCHAR(200)")


def downgrade() -> None:
    op.execute("ALTER TABLE organizations DROP COLUMN IF EXISTS report_file_name")
