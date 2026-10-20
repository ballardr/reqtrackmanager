"""Pending invites may have no organisation

Revision ID: 0103
Revises: 0102
Create Date: 2026-10-20

`pending_invites.organization_id` becomes nullable: a server administrator can invite a person who
joins no organisation yet, the same shape as an always-on self-signup. Existing rows keep their
organisation. Dropping a NOT NULL is idempotent, so a database built from the current models passes.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0103"
down_revision: str | None = "0102"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE pending_invites ALTER COLUMN organization_id DROP NOT NULL")


def downgrade() -> None:
    # Organisation-less invites have nothing to restore into the NOT NULL column; drop them first.
    op.execute("DELETE FROM pending_invites WHERE organization_id IS NULL")
    op.execute("ALTER TABLE pending_invites ALTER COLUMN organization_id SET NOT NULL")
