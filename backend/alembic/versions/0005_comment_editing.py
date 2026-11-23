"""Comment editing

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-10

- `review_comments.edited_at`: nullable timestamp, set only when a comment body is changed through
  `PATCH .../comments/{id}`. It is not derived by comparing `created_at` and `updated_at`:
  `TimestampMixin`'s two `default=utcnow` callables can differ by microseconds on one INSERT, which
  would make a new comment read as edited.

`IF NOT EXISTS`, as in 0002.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE review_comments ADD COLUMN IF NOT EXISTS edited_at TIMESTAMPTZ")


def downgrade() -> None:
    op.execute("ALTER TABLE review_comments DROP COLUMN IF EXISTS edited_at")
