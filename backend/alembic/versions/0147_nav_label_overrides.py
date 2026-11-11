"""Navigation name overrides

Revision ID: 0147
Revises: 0146
Create Date: 2026-11-07

Adds `projects.nav_label_overrides` and `organizations.nav_label_overrides` (navigation names by stable key). An
empty map means every entry keeps its built-in name, so nothing changes for an existing project or organisation.
Guarded so a database built from the current models passes.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0147"
down_revision: str | None = "0146"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE projects ADD COLUMN IF NOT EXISTS nav_label_overrides JSONB NOT NULL DEFAULT '{}'::jsonb")
    op.execute("ALTER TABLE organizations ADD COLUMN IF NOT EXISTS nav_label_overrides JSONB NOT NULL DEFAULT '{}'::jsonb")


def downgrade() -> None:
    op.execute("ALTER TABLE organizations DROP COLUMN IF EXISTS nav_label_overrides")
    op.execute("ALTER TABLE projects DROP COLUMN IF EXISTS nav_label_overrides")
