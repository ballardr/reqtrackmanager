"""Module sub-component enablement

Revision ID: 0049
Revises: 0048
Create Date: 2026-09-28

Adds the two-tier gating tables for `app.modules.registry.ModuleSubComponentDefinition`
(`is_module_subcomponent_enabled`/`is_org_module_subcomponent_enabled`): per-sub-component toggling one
tier below whole-module enablement (`organization_modules`).

- `organization_module_subcomponent_defaults` (`app.models.module.OrganizationModuleSubComponentDefault`):
  org-tier default, mirroring `organization_modules` with a `subcomponent_key` column.
- `project_module_subcomponent_enablements` (`app.models.module.ProjectModuleSubComponentEnablement`):
  project-tier override.

Both are explicit-override-only (an absent row falls back to the org default, then the registry's
`default_enabled`); no backfill.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0049"
down_revision: str | None = "0048"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS organization_module_subcomponent_defaults (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            module_key VARCHAR(100) NOT NULL,
            subcomponent_key VARCHAR(100) NOT NULL,
            enabled BOOLEAN NOT NULL,
            updated_by UUID REFERENCES users(id),
            UNIQUE (organization_id, module_key, subcomponent_key)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_organization_module_subcomponent_defaults_organization_id "
        "ON organization_module_subcomponent_defaults (organization_id)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS project_module_subcomponent_enablements (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            module_key VARCHAR(100) NOT NULL,
            subcomponent_key VARCHAR(100) NOT NULL,
            enabled BOOLEAN NOT NULL,
            updated_by UUID REFERENCES users(id),
            UNIQUE (project_id, module_key, subcomponent_key)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_project_module_subcomponent_enablements_project_id "
        "ON project_module_subcomponent_enablements (project_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS project_module_subcomponent_enablements")
    op.execute("DROP TABLE IF EXISTS organization_module_subcomponent_defaults")
