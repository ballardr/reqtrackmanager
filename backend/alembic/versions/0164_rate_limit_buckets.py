"""`rate_limit_buckets`: token buckets shared by every worker for the unauthenticated and expensive routes.

Revision ID: 0164
Revises: 0163
Create Date: 2026-11-10

Guarded so a database built from the current models passes.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0164"
down_revision: str | None = "0163"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "CREATE TABLE IF NOT EXISTS rate_limit_buckets ("
        "bucket VARCHAR(300) PRIMARY KEY, tokens DOUBLE PRECISION NOT NULL, updated_at TIMESTAMPTZ NOT NULL)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS rate_limit_buckets")
