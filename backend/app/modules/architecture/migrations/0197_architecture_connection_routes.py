"""System Architecture: a route per connection

Revision ID: 0197
Revises: 0196
Create Date: 2026-11-17

`architecture_diagram_anchors` gains `connection_id` (deleting the connection deletes the row). A row with a connection is
that connection's own route, drawn as a line of its own apart from the line its pair of boxes shares; a row without one is
the pair's route as before. The pair's uniqueness now holds for pair rows only, a connection has one route per diagram, and a
connection's route may leave both ends automatic with no vertices (it is then only a line of its own). Every existing row is
a pair's and is unchanged.

The downgrade removes the connection routes (the earlier table has nowhere to keep them) and restores the earlier constraints.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0197"
down_revision: str | None = "0196"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SOMETHING_SET = "source_point IS NOT NULL OR target_point IS NOT NULL OR jsonb_array_length(points) > 0"


def upgrade() -> None:
    op.execute(
        "ALTER TABLE architecture_diagram_anchors ADD COLUMN IF NOT EXISTS connection_id UUID "
        "REFERENCES architecture_connections(id) ON DELETE CASCADE"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_architecture_diagram_anchors_connection_id "
        "ON architecture_diagram_anchors (connection_id)"
    )
    op.execute("ALTER TABLE architecture_diagram_anchors DROP CONSTRAINT IF EXISTS uq_architecture_diagram_anchors")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_architecture_diagram_anchors ON architecture_diagram_anchors "
        "(diagram_id, source_element_id, target_element_id) WHERE connection_id IS NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_architecture_diagram_anchors_connection ON architecture_diagram_anchors "
        "(diagram_id, connection_id) WHERE connection_id IS NOT NULL"
    )
    op.execute("ALTER TABLE architecture_diagram_anchors DROP CONSTRAINT IF EXISTS ck_architecture_diagram_anchors_something_set")
    op.execute(
        "ALTER TABLE architecture_diagram_anchors ADD CONSTRAINT ck_architecture_diagram_anchors_something_set "
        f"CHECK (connection_id IS NOT NULL OR {_SOMETHING_SET})"
    )


def downgrade() -> None:
    op.execute("DELETE FROM architecture_diagram_anchors WHERE connection_id IS NOT NULL")
    op.execute("ALTER TABLE architecture_diagram_anchors DROP CONSTRAINT IF EXISTS ck_architecture_diagram_anchors_something_set")
    op.execute(
        "ALTER TABLE architecture_diagram_anchors ADD CONSTRAINT ck_architecture_diagram_anchors_something_set "
        f"CHECK ({_SOMETHING_SET})"
    )
    op.execute("DROP INDEX IF EXISTS uq_architecture_diagram_anchors_connection")
    op.execute("DROP INDEX IF EXISTS uq_architecture_diagram_anchors")
    op.execute(
        "ALTER TABLE architecture_diagram_anchors ADD CONSTRAINT uq_architecture_diagram_anchors "
        "UNIQUE (diagram_id, source_element_id, target_element_id)"
    )
    op.execute("DROP INDEX IF EXISTS ix_architecture_diagram_anchors_connection_id")
    op.execute("ALTER TABLE architecture_diagram_anchors DROP COLUMN IF EXISTS connection_id")
