"""System Architecture state symbol label length

Revision ID: 0192
Revises: 0191
Create Date: 2026-11-16

Widens `architecture_states.label` from 40 to 256 characters, so a symbol can carry a full question or condition. No stored
label changes. Downgrading cuts any longer label to its first 40 characters.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0192"
down_revision: str | None = "0191"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE architecture_states ALTER COLUMN label TYPE VARCHAR(256)")


def downgrade() -> None:
    op.execute("ALTER TABLE architecture_states ALTER COLUMN label TYPE VARCHAR(40) USING left(label, 40)")
