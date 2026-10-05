"""Project-level override of whole-module enablement (Module 0 — Platform Foundations, Phase 5)

Revision ID: 0050
Revises: 0049
Create Date: 2026-09-28

Adds `project_module_enablements` (`app.models.module.ProjectModuleEnablement`)
— a project-tier override of whole-module enablement itself, one tier below
`organization_modules` (migration for compliance-module-plan.md Phase 1),
mirroring that table's own shape (`project_id`/`module_key`/`enabled`/
`updated_by`, unique on `(project_id, module_key)`). This is a genuinely
new capability, not previously covered by any table: whole-module
enablement had no project-level override at all before this migration —
only Module 0 Phase 4's own sub-component layer
(`organization_module_subcomponent_defaults`/
`project_module_subcomponent_enablements`, migration 0049) got one.

No backfill needed — explicit-override-only (absence of a row falls back
to the organisation's own `organization_modules` row, then the registry's
`default_enabled`), and no project-level whole-module override existed
anywhere before this migration.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0050"
down_revision: str | None = "0049"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS project_module_enablements (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            module_key VARCHAR(100) NOT NULL,
            enabled BOOLEAN NOT NULL,
            updated_by UUID REFERENCES users(id),
            UNIQUE (project_id, module_key)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_project_module_enablements_project_id "
        "ON project_module_enablements (project_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS project_module_enablements")
