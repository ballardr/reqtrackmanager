"""Announcement dismissible switch

Revision ID: 0153
Revises: 0152
Create Date: 2026-11-09

Adds `announcements.dismissible` (default true, so every existing message keeps its close control). Guarded so a
database built from the current models passes.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0153"
down_revision: str | None = "0152"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE announcements ADD COLUMN IF NOT EXISTS dismissible BOOLEAN NOT NULL DEFAULT TRUE")


def downgrade() -> None:
    op.execute("ALTER TABLE announcements DROP COLUMN IF EXISTS dismissible")
