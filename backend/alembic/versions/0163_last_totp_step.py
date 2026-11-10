"""`users.last_totp_step`: the latest TOTP time step accepted, so a code cannot be used twice.

Revision ID: 0163
Revises: 0162
Create Date: 2026-11-10

Nullable; null means no code has been accepted yet. Guarded so a database built from the current models passes.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0163"
down_revision: str | None = "0162"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_totp_step BIGINT")


def downgrade() -> None:
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS last_totp_step")
