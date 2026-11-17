"""System Architecture line shape

Revision ID: 0198
Revises: 0197
Create Date: 2026-11-17

Replaces the `smooth` flag of a drawn line with a shape: Straight, Curved or Spline. On `architecture_diagram_anchors`,
`architecture_transitions` and `architecture_note_leaders` the new `line_shape` is nullable, where null follows the diagram's
default; a line that was smooth becomes Spline, and one that was not becomes null (so it keeps drawing as it did, and follows
the diagram if its default is changed later). `architecture_diagrams` and `architecture_state_machine_diagrams` gain the
default, `line_shape`, set to straight so no diagram changes on upgrade. A route that only sets a shape is a stored row, so the
anchors "something is set" rule counts it.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0198"
down_revision: str | None = "0197"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_LINES = ("architecture_diagram_anchors", "architecture_transitions", "architecture_note_leaders")
_DIAGRAMS = ("architecture_diagrams", "architecture_state_machine_diagrams")
_SOMETHING_SET = (
    "connection_id IS NOT NULL OR source_point IS NOT NULL OR target_point IS NOT NULL OR jsonb_array_length(points) > 0"
)


def _constraint(table: str, name: str, rule: str) -> None:
    op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {name}")
    op.execute(f"ALTER TABLE {table} ADD CONSTRAINT {name} CHECK ({rule})")


def _has_column(table: str, column: str) -> bool:
    """Whether `table` has `column` (a test database built from the models never had `smooth`)."""
    return any(c["name"] == column for c in sa.inspect(op.get_bind()).get_columns(table))


def upgrade() -> None:
    for table in _LINES:
        op.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS line_shape VARCHAR(16)")
        if _has_column(table, "smooth"):
            op.execute(f"UPDATE {table} SET line_shape = 'spline' WHERE smooth AND line_shape IS NULL")
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS smooth")
        _constraint(table, f"ck_{table}_line_shape", "line_shape IS NULL OR line_shape IN ('straight', 'curved', 'spline')")
    for table in _DIAGRAMS:
        op.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS line_shape VARCHAR(16) NOT NULL DEFAULT 'straight'")
        _constraint(table, f"ck_{table}_line_shape", "line_shape IN ('straight', 'curved', 'spline')")
    _constraint(
        "architecture_diagram_anchors", "ck_architecture_diagram_anchors_something_set", f"{_SOMETHING_SET} OR line_shape IS NOT NULL",
    )


def downgrade() -> None:
    # A row that held only a shape has nothing left to say once it goes; a Curved line becomes straight, a Spline smooth.
    op.execute(
        "DELETE FROM architecture_diagram_anchors WHERE connection_id IS NULL AND source_point IS NULL AND target_point IS NULL "
        "AND jsonb_array_length(points) = 0"
    )
    for table in _LINES:
        op.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS smooth BOOLEAN NOT NULL DEFAULT false")
        if _has_column(table, "line_shape"):
            op.execute(f"UPDATE {table} SET smooth = true WHERE line_shape = 'spline'")
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS ck_{table}_line_shape")
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS line_shape")
    for table in _DIAGRAMS:
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS ck_{table}_line_shape")
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS line_shape")
    _constraint("architecture_diagram_anchors", "ck_architecture_diagram_anchors_something_set", _SOMETHING_SET)
