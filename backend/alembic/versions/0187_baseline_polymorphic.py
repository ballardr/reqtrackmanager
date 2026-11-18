"""Polymorphic baselines: `baselines.kind`, a nullable `stage_id`, and typed `baseline_items`.

Revision ID: 0187
Revises: 0186
Create Date: 2026-11-14

A baseline can now be taken manually (no stage) and can hold a module's records as well as requirements. `kind` is
`stage` for every existing row. A `baseline_items` row gains `item_type` (`requirement` for every existing row),
`item_id` (backfilled from `requirement_id`) and a JSON `snapshot`; the two requirement columns become nullable, and a
check constraint keeps the two shapes apart. Constraints are dropped first so a database built from the current models
passes.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0187"
down_revision: str | None = "0186"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE baselines
            ADD COLUMN IF NOT EXISTS kind VARCHAR(10) NOT NULL DEFAULT 'stage',
            ALTER COLUMN stage_id DROP NOT NULL,
            DROP CONSTRAINT IF EXISTS ck_baselines_kind_stage,
            ADD CONSTRAINT ck_baselines_kind_stage CHECK (
                (kind = 'stage' AND stage_id IS NOT NULL)
                OR (kind = 'manual' AND stage_id IS NULL AND component_id IS NULL)
            )
        """
    )
    op.execute(
        """
        ALTER TABLE baseline_items
            ADD COLUMN IF NOT EXISTS item_type VARCHAR(40) NOT NULL DEFAULT 'requirement',
            ADD COLUMN IF NOT EXISTS item_id UUID,
            ADD COLUMN IF NOT EXISTS snapshot JSONB,
            ALTER COLUMN requirement_id DROP NOT NULL,
            ALTER COLUMN requirement_version_id DROP NOT NULL
        """
    )
    op.execute("UPDATE baseline_items SET item_id = requirement_id WHERE item_id IS NULL AND requirement_id IS NOT NULL")
    op.execute(
        """
        ALTER TABLE baseline_items
            DROP CONSTRAINT IF EXISTS uq_baseline_items_baseline_type_item,
            DROP CONSTRAINT IF EXISTS ck_baseline_items_shape,
            ADD CONSTRAINT uq_baseline_items_baseline_type_item UNIQUE (baseline_id, item_type, item_id),
            ADD CONSTRAINT ck_baseline_items_shape CHECK (
                (item_type = 'requirement' AND requirement_id IS NOT NULL AND requirement_version_id IS NOT NULL)
                OR (item_type <> 'requirement' AND requirement_id IS NULL AND requirement_version_id IS NULL
                    AND snapshot IS NOT NULL)
            )
        """
    )


def downgrade() -> None:
    op.execute("DELETE FROM baseline_items WHERE item_type <> 'requirement'")
    op.execute("DELETE FROM baselines WHERE kind = 'manual'")
    op.execute(
        """
        ALTER TABLE baseline_items
            DROP CONSTRAINT IF EXISTS ck_baseline_items_shape,
            DROP CONSTRAINT IF EXISTS uq_baseline_items_baseline_type_item,
            ALTER COLUMN requirement_version_id SET NOT NULL,
            ALTER COLUMN requirement_id SET NOT NULL,
            DROP COLUMN IF EXISTS snapshot,
            DROP COLUMN IF EXISTS item_id,
            DROP COLUMN IF EXISTS item_type
        """
    )
    op.execute(
        """
        ALTER TABLE baselines
            DROP CONSTRAINT IF EXISTS ck_baselines_kind_stage,
            ALTER COLUMN stage_id SET NOT NULL,
            DROP COLUMN IF EXISTS kind
        """
    )
