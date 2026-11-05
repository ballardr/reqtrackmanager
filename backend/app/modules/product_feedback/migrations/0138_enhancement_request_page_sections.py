"""A project's default order for the sections of a request page

Revision ID: 0138
Revises: 0137
Create Date: 2026-11-05

Adds the nullable `project_feedback_settings.request_page_sections` (a JSON list of section keys). Null is the
built-in order, so no existing project changes.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0138"
down_revision: str | None = "0137"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE project_feedback_settings ADD COLUMN IF NOT EXISTS request_page_sections JSON")


def downgrade() -> None:
    op.execute("ALTER TABLE project_feedback_settings DROP COLUMN IF EXISTS request_page_sections")
