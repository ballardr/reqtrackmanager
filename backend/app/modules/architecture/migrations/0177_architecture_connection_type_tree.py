"""System Architecture connection type tree: parent links between connection types

Revision ID: 0177
Revises: 0176
Create Date: 2026-11-12

Adds `architecture_connection_type_parents` (child, parent), so a connection type can sit under several parents to
any depth and a group is itself a usable type. Deleting either type removes the edge. The service refuses a cycle and
a chain deeper than 12; the CHECK here only stops a type being its own parent.

Nothing is seeded: a fresh organisation gets the default groups from the service, and an existing organisation adds
its own groups. Guarded so a database built from the current models passes.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0177"
down_revision: str | None = "0176"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS architecture_connection_type_parents (
            child_id UUID NOT NULL REFERENCES architecture_connection_types(id) ON DELETE CASCADE,
            parent_id UUID NOT NULL REFERENCES architecture_connection_types(id) ON DELETE CASCADE,
            PRIMARY KEY (child_id, parent_id),
            CONSTRAINT ck_architecture_connection_type_parents_not_self CHECK (child_id <> parent_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_architecture_connection_type_parents_parent_id "
        "ON architecture_connection_type_parents (parent_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS architecture_connection_type_parents")
