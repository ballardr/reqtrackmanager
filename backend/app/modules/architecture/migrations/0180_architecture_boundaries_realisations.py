"""System Architecture boundary boxes and realisations

Revision ID: 0180
Revises: 0179
Create Date: 2026-11-13

Adds `architecture_diagram_boundaries` (a box inside a scoped diagram standing for one outer connection) and
`architecture_connection_realisations` (an inner connection marked as realising an outer one). Deleting a diagram or a
connection removes its rows. Nothing is seeded.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0180"
down_revision: str | None = "0179"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS architecture_diagram_boundaries (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            diagram_id UUID NOT NULL REFERENCES architecture_diagrams(id) ON DELETE CASCADE,
            connection_id UUID NOT NULL REFERENCES architecture_connections(id) ON DELETE CASCADE,
            x DOUBLE PRECISION NOT NULL DEFAULT 0,
            y DOUBLE PRECISION NOT NULL DEFAULT 0,
            width DOUBLE PRECISION NOT NULL DEFAULT 120,
            height DOUBLE PRECISION NOT NULL DEFAULT 48,
            CONSTRAINT uq_architecture_diagram_boundaries UNIQUE (diagram_id, connection_id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS architecture_connection_realisations (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            inner_connection_id UUID NOT NULL REFERENCES architecture_connections(id) ON DELETE CASCADE,
            outer_connection_id UUID NOT NULL REFERENCES architecture_connections(id) ON DELETE CASCADE,
            CONSTRAINT uq_architecture_connection_realisations UNIQUE (inner_connection_id, outer_connection_id),
            CONSTRAINT ck_architecture_connection_realisations_distinct CHECK (inner_connection_id <> outer_connection_id)
        )
        """
    )
    for table, column in (
        ("architecture_diagram_boundaries", "diagram_id"), ("architecture_diagram_boundaries", "connection_id"),
        ("architecture_connection_realisations", "inner_connection_id"),
        ("architecture_connection_realisations", "outer_connection_id"),
    ):
        op.execute(f"CREATE INDEX IF NOT EXISTS ix_{table}_{column} ON {table} ({column})")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS architecture_connection_realisations")
    op.execute("DROP TABLE IF EXISTS architecture_diagram_boundaries")
