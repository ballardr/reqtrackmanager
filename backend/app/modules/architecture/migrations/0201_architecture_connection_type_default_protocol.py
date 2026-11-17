"""System Architecture: a connection type's default protocol

Revision ID: 0201
Revises: 0200
Create Date: 2026-11-17

Adds `default_protocol` to `architecture_connection_types`: the protocol a new connection of the type starts with.
It is blank by default and never applied to a connection that exists, so no stored record changes on upgrade.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0201"
down_revision: str | None = "0200"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE architecture_connection_types ADD COLUMN IF NOT EXISTS default_protocol VARCHAR(200) NOT NULL DEFAULT ''")


def downgrade() -> None:
    op.execute("ALTER TABLE architecture_connection_types DROP COLUMN IF EXISTS default_protocol")
