"""A note on each request merge

Revision ID: 0139
Revises: 0138
Create Date: 2026-11-05

Adds `enhancement_request_merges.note`: why the merged requests are the same ask. The merge dialog always offered a
note, but it was not kept; merges made before this have an empty one.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0139"
down_revision: str | None = "0138"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE enhancement_request_merges ADD COLUMN IF NOT EXISTS note TEXT NOT NULL DEFAULT ''")


def downgrade() -> None:
    op.execute("ALTER TABLE enhancement_request_merges DROP COLUMN IF EXISTS note")
