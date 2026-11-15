"""System Architecture state symbol label

Revision ID: 0188
Revises: 0187
Create Date: 2026-11-15

Adds `label` to `architecture_states`: a short plain-text line drawn inside an initial, final or choice symbol. Existing
states get an empty label, so nothing changes on screen.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0188"
down_revision: str | None = "0187"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE architecture_states ADD COLUMN IF NOT EXISTS label VARCHAR(40) NOT NULL DEFAULT ''")


def downgrade() -> None:
    op.execute("ALTER TABLE architecture_states DROP COLUMN IF EXISTS label")
