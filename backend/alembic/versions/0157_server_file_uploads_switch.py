"""Deployment-wide file upload switch

Revision ID: 0157
Revises: 0156
Create Date: 2026-11-10

Adds `server_settings.file_uploads_enabled` (on, so an upgrade changes nothing). Seeds nothing. Guarded so a database
built from the current models passes.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0157"
down_revision: str | None = "0156"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE server_settings ADD COLUMN IF NOT EXISTS file_uploads_enabled BOOLEAN NOT NULL DEFAULT true")


def downgrade() -> None:
    op.execute("ALTER TABLE server_settings DROP COLUMN IF EXISTS file_uploads_enabled")
