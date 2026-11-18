"""System Architecture state label position

Revision ID: 0193
Revises: 0192
Create Date: 2026-11-16

Adds `label_position` to `architecture_states`: where an initial, final or choice symbol's label is drawn (`inside`, `left`,
`right`, `above` or `below`). Existing states get `inside`, so no stored diagram changes on upgrade.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0193"
down_revision: str | None = "0192"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE architecture_states ADD COLUMN IF NOT EXISTS label_position VARCHAR(16) NOT NULL DEFAULT 'inside'")
    op.execute("ALTER TABLE architecture_states DROP CONSTRAINT IF EXISTS ck_architecture_states_label_position")
    op.execute(
        "ALTER TABLE architecture_states ADD CONSTRAINT ck_architecture_states_label_position "
        "CHECK (label_position IN ('inside', 'left', 'right', 'above', 'below'))"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE architecture_states DROP CONSTRAINT IF EXISTS ck_architecture_states_label_position")
    op.execute("ALTER TABLE architecture_states DROP COLUMN IF EXISTS label_position")
