"""Organisation-tier default project state for a module

Revision ID: 0055
Revises: 0054
Create Date: 2026-09-29

Adds `organization_modules.default_project_enabled`, a third, independent tier between `enabled` (a hard
floor: `False` means no project may use the module) and a project's own
`ProjectModuleEnablement.enabled` override (**Decided by: User**; docs/decisions.md). An org admin can
make a module available but off by default, with an individual project manager able to opt in;
`enabled` alone cannot express that because it is the floor, not the default a project inherits.

Backfilled to each row's `enabled` value, so no effective state changes.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0055"
down_revision: str | None = "0054"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE organization_modules ADD COLUMN IF NOT EXISTS "
        "default_project_enabled BOOLEAN NOT NULL DEFAULT true"
    )
    # Backfill: match each existing row's own current `enabled` value, so
    # no organisation's effective project-default changes as a result of
    # this migration alone.
    op.execute("UPDATE organization_modules SET default_project_enabled = enabled")


def downgrade() -> None:
    op.execute("ALTER TABLE organization_modules DROP COLUMN IF EXISTS default_project_enabled")
