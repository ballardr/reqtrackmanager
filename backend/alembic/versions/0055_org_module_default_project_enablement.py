"""Organisation-tier default project state for a module (Module 0 — Platform Foundations, Phase 5 correction)

Revision ID: 0055
Revises: 0054
Create Date: 2026-09-29

Adds `organization_modules.default_project_enabled` — a third, independent
tier between the existing `enabled` (hard on/off, an absolute floor: `False`
means no project may use this module at all, no override possible) and a
project's own `ProjectModuleEnablement.enabled` override (Decided by: User,
2026-09-29 — see `docs/decisions.md`'s dated entry and
`docs/plans/module-00-platform-foundations-plan.md`'s Phase 5 correction
note for the full reasoning this migration implements).

This is the piece that was missing from Phase 5's original design: an org
admin needs to be able to say "this module is available (not hard-
disabled), but off by default for every project — an individual project
manager can still opt in for their own project if they want it" — a case
the original two-tier (`enabled` + symmetric project override) design
couldn't express, since `enabled` alone conflated "hard floor" and "default
a project inherits."

Backfilled to match each existing row's own current `enabled` value, so no
organisation's or project's effective state changes as a result of this
migration alone — a module already on today stays effectively on-by-default
for every project of that organisation immediately after this deploys.
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
