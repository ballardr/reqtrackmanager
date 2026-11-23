"""Project-level override of whole-module enablement

Revision ID: 0050
Revises: 0049
Create Date: 2026-09-28

Adds `project_module_enablements` (`app.models.module.ProjectModuleEnablement`): a project-tier override
of whole-module enablement, one tier below `organization_modules` and with the same shape
(`project_id`/`module_key`/`enabled`/`updated_by`, unique on `(project_id, module_key)`). The
sub-component layer has its own project override in 0049.

Explicit-override-only (an absent row falls back to the organisation's `organization_modules` row, then
the registry's `default_enabled`); no backfill.
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
