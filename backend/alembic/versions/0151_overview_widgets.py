"""Project overview widget layouts

Revision ID: 0151
Revises: 0150
Create Date: 2026-11-08

Adds `projects.overview_widgets` and `organizations.overview_widgets` (a layout object `{scope, widgets}`; SQL NULL
means none, so the nearest ancestor's, the organisation's or the built-in layout applies). Nothing changes for an
existing project or organisation. Guarded so a database built from the current models passes.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0151"
down_revision: str | None = "0150"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE projects ADD COLUMN IF NOT EXISTS overview_widgets JSONB")
    op.execute("ALTER TABLE organizations ADD COLUMN IF NOT EXISTS overview_widgets JSONB")


def downgrade() -> None:
    op.execute("ALTER TABLE organizations DROP COLUMN IF EXISTS overview_widgets")
    op.execute("ALTER TABLE projects DROP COLUMN IF EXISTS overview_widgets")
