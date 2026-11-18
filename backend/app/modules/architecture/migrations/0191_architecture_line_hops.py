"""System Architecture line hops

Revision ID: 0191
Revises: 0190
Create Date: 2026-11-16

Adds `line_hops` to `architecture_diagrams` (a block diagram) and `architecture_state_machine_diagrams` (a state machine
diagram): when true a line that crosses another is drawn with a small arc over it, on the screen and in the exports. Existing
diagrams get false, so none changes on upgrade.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0191"
down_revision: str | None = "0190"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = ("architecture_diagrams", "architecture_state_machine_diagrams")


def upgrade() -> None:
    for table in _TABLES:
        op.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS line_hops BOOLEAN NOT NULL DEFAULT false")


def downgrade() -> None:
    for table in _TABLES:
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS line_hops")
