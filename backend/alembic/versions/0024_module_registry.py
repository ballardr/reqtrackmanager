"""Module registry gating tables

Revision ID: 0024
Revises: 0023
Create Date: 2026-09-04

Two-tier module gating for the modular feature system:

- `organization_module_entitlements` (`app.models.module.OrganizationModuleEntitlement`): server-tier
  override of whether an organisation is entitled to a module (the licensing lever, managed by
  `SERVER_ADMIN`/`MODULE_ADMINISTRATOR`).
- `organization_modules` (`app.models.module.OrganizationModuleEnablement`): org-tier override of
  whether an org admin has enabled an entitled module.

Both tables hold explicit overrides only; an absent row falls back to
`ServerSettings.default_module_entitlement_policy` (entitlement) or `ModuleDefinition.default_enabled`
(enablement) in `app.modules.registry`'s `is_module_entitled`/`is_module_enabled`. No backfill.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS organization_module_entitlements (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            module_key VARCHAR(100) NOT NULL,
            entitled BOOLEAN NOT NULL,
            updated_by UUID REFERENCES users(id),
            UNIQUE (organization_id, module_key)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_organization_module_entitlements_organization_id "
        "ON organization_module_entitlements (organization_id)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS organization_modules (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            module_key VARCHAR(100) NOT NULL,
            enabled BOOLEAN NOT NULL,
            updated_by UUID REFERENCES users(id),
            UNIQUE (organization_id, module_key)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_organization_modules_organization_id "
        "ON organization_modules (organization_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS organization_modules")
    op.execute("DROP TABLE IF EXISTS organization_module_entitlements")
