"""Sub-component hard floor vs. project default (Module 0 — Platform Foundations)

Revision ID: 0056
Revises: 0055
Create Date: 2026-10-04

Adds `organization_module_subcomponent_defaults.default_project_enabled`,
giving sub-components the same two org-level levers whole modules got in
0055: `enabled` becomes a hard floor (Off reaches every project), and
`default_project_enabled` is the value copied into a project at creation
(Decided by: User, 2026-10-04 — see `docs/decisions.md`).

Backfilled to each row's current `enabled`, so no effective state changes.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0056"
down_revision: str | None = "0055"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Adds and backfills the `default_project_enabled` column."""
    op.execute(
        "ALTER TABLE organization_module_subcomponent_defaults ADD COLUMN IF NOT EXISTS "
        "default_project_enabled BOOLEAN NOT NULL DEFAULT true"
    )
    op.execute("UPDATE organization_module_subcomponent_defaults SET default_project_enabled = enabled")


def downgrade() -> None:
    """Drops the `default_project_enabled` column."""
    op.execute(
        "ALTER TABLE organization_module_subcomponent_defaults DROP COLUMN IF EXISTS default_project_enabled"
    )
