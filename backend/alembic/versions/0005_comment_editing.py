"""Comment editing

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-10

- `review_comments.edited_at`: nullable timestamp, set only when a comment's
  body is actually changed via `PATCH .../comments/{id}` — left null at
  creation (deliberately not derived by comparing `created_at`/`updated_at`,
  since `TimestampMixin`'s two independent `default=utcnow` callables can
  each resolve a few microseconds apart on the very same INSERT, which would
  make a brand-new, never-edited comment intermittently read as "edited").

`IF NOT EXISTS`, same reason 0002-0004 use it: a brand-new database's
`create_all()` already creates this column against the current model class,
so a plain `ADD COLUMN` would fail there with "already exists"; an
already-migrated database from before this revision is genuinely missing it.
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
