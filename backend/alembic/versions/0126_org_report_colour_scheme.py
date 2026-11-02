"""Organisation report colour scheme: organizations.report_colour_scheme

Revision ID: 0126
Revises: 0125
Create Date: 2026-11-02

Adds `organizations.report_colour_scheme` (JSONB, NULL = none set): the organisation's named report colours, which a custom
layout with no scheme of its own resolves colour names by. Guarded: a database built from the current models has it.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0126"
down_revision: str | None = "0125"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE organizations ADD COLUMN IF NOT EXISTS report_colour_scheme JSONB")


def downgrade() -> None:
    op.execute("ALTER TABLE organizations DROP COLUMN IF EXISTS report_colour_scheme")
