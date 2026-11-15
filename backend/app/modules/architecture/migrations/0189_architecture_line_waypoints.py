"""System Architecture waypoints on lines

Revision ID: 0189
Revises: 0188
Create Date: 2026-11-15

Adds `points` (an ordered JSON list of `{x, y}` vertices in canvas units) and `smooth` (a curve through them) to
`architecture_diagram_anchors` (a block diagram line) and `architecture_transitions` (a state machine line). Existing lines
get no points and are drawn exactly as before. The anchors row's "something is set" rule now also counts points, so a line
with vertices and automatic attach points is stored.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0189"
down_revision: str | None = "0188"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for table in ("architecture_diagram_anchors", "architecture_transitions"):
        op.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS points JSONB NOT NULL DEFAULT '[]'::jsonb")
        op.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS smooth BOOLEAN NOT NULL DEFAULT false")
    op.execute("ALTER TABLE architecture_diagram_anchors DROP CONSTRAINT IF EXISTS ck_architecture_diagram_anchors_something_set")
    op.execute(
        "ALTER TABLE architecture_diagram_anchors ADD CONSTRAINT ck_architecture_diagram_anchors_something_set CHECK "
        "(source_point IS NOT NULL OR target_point IS NOT NULL OR jsonb_array_length(points) > 0)"
    )


def downgrade() -> None:
    # A row that held only vertices has nothing left to say once they go.
    op.execute("DELETE FROM architecture_diagram_anchors WHERE source_point IS NULL AND target_point IS NULL")
    op.execute("ALTER TABLE architecture_diagram_anchors DROP CONSTRAINT IF EXISTS ck_architecture_diagram_anchors_something_set")
    op.execute(
        "ALTER TABLE architecture_diagram_anchors ADD CONSTRAINT ck_architecture_diagram_anchors_something_set CHECK "
        "(source_point IS NOT NULL OR target_point IS NOT NULL)"
    )
    for table in ("architecture_diagram_anchors", "architecture_transitions"):
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS smooth")
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS points")
