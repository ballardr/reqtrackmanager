"""Custom scoring axes: scored per target or for the whole record

Revision ID: 0149
Revises: 0148
Create Date: 2026-11-08

Adds `scoring_custom_axes.per_target`, which says whether a custom axis on a scheme with targets (Pain Points,
scored per persona) is scored separately for each target or once for the whole record. Existing axes belong to
schemes that have no targets, so they take `false`. Guarded so a database built from the current models passes.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0149"
down_revision: str | None = "0148"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE scoring_custom_axes ADD COLUMN IF NOT EXISTS per_target BOOLEAN NOT NULL DEFAULT false")


def downgrade() -> None:
    op.execute("ALTER TABLE scoring_custom_axes DROP COLUMN IF EXISTS per_target")
