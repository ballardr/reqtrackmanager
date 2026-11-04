"""Enhancement request scoring levels

Revision ID: 0132
Revises: 0131
Create Date: 2026-11-04

Adds the four scoring-level references (Reach, Impact, Confidence, Effort) to `enhancement_request_versions`.
They reference the organisation's `enhancement_request` scoring levels and are nulled if a level is deleted.
The scoring levels themselves are seeded by core at process start, so nothing is inserted here.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0132"
down_revision: str | None = "0131"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COLUMNS = ("reach_level_id", "impact_level_id", "confidence_level_id", "effort_level_id")


def upgrade() -> None:
    for column in _COLUMNS:
        op.execute(
            f"ALTER TABLE enhancement_request_versions ADD COLUMN IF NOT EXISTS {column} UUID "
            "REFERENCES scoring_levels(id) ON DELETE SET NULL"
        )


def downgrade() -> None:
    for column in _COLUMNS:
        op.execute(f"ALTER TABLE enhancement_request_versions DROP COLUMN IF EXISTS {column}")
