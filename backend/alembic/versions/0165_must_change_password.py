"""`users.must_change_password`: an administrator-set password must be changed at the first sign-in.

Revision ID: 0165
Revises: 0164
Create Date: 2026-11-10

Existing accounts are unaffected (false). Guarded so a database built from the current models passes.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0165"
down_revision: str | None = "0164"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS must_change_password BOOLEAN NOT NULL DEFAULT false")


def downgrade() -> None:
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS must_change_password")
