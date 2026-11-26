"""The date a stage's review deadline was last reminded

Revision ID: 0211
Revises: 0210
Create Date: 2026-11-26

A nullable date on `project_stages`, so a review deadline is reminded once and a changed deadline is reminded again.
Nothing is backfilled: a stage already in review with a deadline inside the reminder window is reminded on the next
sweep. Guarded so a database built from the current models passes.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0211"
down_revision: str | None = "0210"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE project_stages ADD COLUMN IF NOT EXISTS review_deadline_reminded_for DATE")


def downgrade() -> None:
    op.execute("ALTER TABLE project_stages DROP COLUMN IF EXISTS review_deadline_reminded_for")
