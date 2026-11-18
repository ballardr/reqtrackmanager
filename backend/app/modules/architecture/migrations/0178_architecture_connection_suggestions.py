"""System Architecture soft guidance: connection types suggested for an element type

Revision ID: 0178
Revises: 0177
Create Date: 2026-11-13

Adds `architecture_element_type_suggestions` (element type, connection type), so an element type can name the
connection types a connection picker lists first. Guidance only: nothing is enforced. Deleting either type removes the
row.

Nothing is seeded: a fresh organisation gets the default suggestions from the service, and an existing organisation
adds its own. Guarded so a database built from the current models passes.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0178"
down_revision: str | None = "0177"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS architecture_element_type_suggestions (
            element_type_id UUID NOT NULL REFERENCES architecture_element_types(id) ON DELETE CASCADE,
            connection_type_id UUID NOT NULL REFERENCES architecture_connection_types(id) ON DELETE CASCADE,
            PRIMARY KEY (element_type_id, connection_type_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_architecture_element_type_suggestions_connection_type_id "
        "ON architecture_element_type_suggestions (connection_type_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS architecture_element_type_suggestions")
