"""System Architecture: show connection names

Revision ID: 0200
Revises: 0199
Create Date: 2026-11-17

Adds `show_connection_names` to `architecture_diagrams`: a diagram setting that draws each connection's name beside its line.
It defaults to false, so no stored diagram changes on upgrade.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0200"
down_revision: str | None = "0199"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE architecture_diagrams ADD COLUMN IF NOT EXISTS show_connection_names BOOLEAN NOT NULL DEFAULT false")


def downgrade() -> None:
    op.execute("ALTER TABLE architecture_diagrams DROP COLUMN IF EXISTS show_connection_names")
