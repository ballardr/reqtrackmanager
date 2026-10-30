"""A file can be marked confidential: file_assets.confidential

Revision ID: 0118
Revises: 0117
Create Date: 2026-10-30

Adds `file_assets.confidential` (default false). A confidential file is never printed by a report's record-images block.
Guarded: a database built from the current models already has it.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0118"
down_revision: str | None = "0117"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE file_assets ADD COLUMN IF NOT EXISTS confidential BOOLEAN NOT NULL DEFAULT false")


def downgrade() -> None:
    op.execute("ALTER TABLE file_assets DROP COLUMN IF EXISTS confidential")
