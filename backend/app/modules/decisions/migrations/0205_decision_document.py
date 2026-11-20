"""Decisions: a long-form Markdown document

Revision ID: 0205
Revises: 0204
Create Date: 2026-11-20

Adds `decisions.document`: the decision written out in full as Markdown (with tables and diagrams), beside the
structured fields. It is empty by default, so no stored record changes on upgrade.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0205"
down_revision: str | None = "0204"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE decisions ADD COLUMN IF NOT EXISTS document TEXT")


def downgrade() -> None:
    op.execute("ALTER TABLE decisions DROP COLUMN IF EXISTS document")
