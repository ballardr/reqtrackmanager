"""Index review comments by their target

Revision ID: 0107
Revises: 0106
Create Date: 2026-10-25

Every comment list and per-record comment count filters `review_comments` on (target_type, target_id), and the
table had no index for it, so each list page scanned every comment in the database. Guarded: a database built from
the current models already has it.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0107"
down_revision: str | None = "0106"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE INDEX IF NOT EXISTS ix_review_comments_target ON review_comments (target_type, target_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_review_comments_target")
