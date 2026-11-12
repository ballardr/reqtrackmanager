"""System Architecture attach points: where a diagram line meets its boxes

Revision ID: 0179
Revises: 0178
Create Date: 2026-11-13

Adds `architecture_diagram_anchors`, one row per drawn line whose ends a person has placed on one of a box's eight attach
points. The row is keyed by the diagram and the pair of placed elements the line joins (a merged or rolled-up line has
one anchor for all it stands for); an end left empty is chosen automatically. Deleting the diagram or either element
removes the row. Nothing is seeded: without a row a line uses the nearest points.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0179"
down_revision: str | None = "0178"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS architecture_diagram_anchors (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            diagram_id UUID NOT NULL REFERENCES architecture_diagrams(id) ON DELETE CASCADE,
            source_element_id UUID NOT NULL REFERENCES architecture_elements(id) ON DELETE CASCADE,
            target_element_id UUID NOT NULL REFERENCES architecture_elements(id) ON DELETE CASCADE,
            source_point VARCHAR(16),
            target_point VARCHAR(16),
            CONSTRAINT uq_architecture_diagram_anchors UNIQUE (diagram_id, source_element_id, target_element_id),
            CONSTRAINT ck_architecture_diagram_anchors_distinct CHECK (source_element_id <> target_element_id),
            CONSTRAINT ck_architecture_diagram_anchors_something_set CHECK (source_point IS NOT NULL OR target_point IS NOT NULL)
        )
        """
    )
    for column in ("diagram_id", "source_element_id", "target_element_id"):
        op.execute(
            f"CREATE INDEX IF NOT EXISTS ix_architecture_diagram_anchors_{column} ON architecture_diagram_anchors ({column})"
        )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS architecture_diagram_anchors")
