"""`users.email_confirmation_pending`: a self-signed-up account that has not yet confirmed its email address.

Revision ID: 0167
Revises: 0166
Create Date: 2026-11-10

False for every existing account (nobody is locked out by the upgrade). Guarded so a database built from the
current models passes.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0167"
down_revision: str | None = "0166"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS email_confirmation_pending BOOLEAN NOT NULL DEFAULT false")


def downgrade() -> None:
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS email_confirmation_pending")
