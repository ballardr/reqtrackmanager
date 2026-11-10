"""Organisation setting `allow_imported_approval_state`: whether a project import may keep imported approval state.

Revision ID: 0162
Revises: 0161
Create Date: 2026-11-10

Default true, so an upgrade changes nothing. Guarded so a database built from the current models passes.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0162"
down_revision: str | None = "0161"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE organizations ADD COLUMN IF NOT EXISTS allow_imported_approval_state BOOLEAN NOT NULL DEFAULT true")


def downgrade() -> None:
    op.execute("ALTER TABLE organizations DROP COLUMN IF EXISTS allow_imported_approval_state")
