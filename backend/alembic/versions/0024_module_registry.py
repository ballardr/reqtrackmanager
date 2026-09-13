"""Module registry gating tables (module system Phase 1)

Revision ID: 0024
Revises: 0023
Create Date: 2026-09-04

Two-tier module gating for the modular feature system
(docs/compliance-module-plan.md Phase 1), sitting on top of Phase 0's
`server_roles`/`default_module_entitlement_policy`:

- `organization_module_entitlements` (`app.models.module.
  OrganizationModuleEntitlement`) — server-tier override of whether an
  organisation is entitled to a module (the licensing/plan lever, managed
  by `SERVER_ADMIN`/`MODULE_ADMINISTRATOR`).
- `organization_modules` (`app.models.module.OrganizationModuleEnablement`)
  — org-tier override of whether an org admin has enabled a module among
  those it's entitled to (the day-to-day switch).

Both are explicit-override-only tables: absence of a row is meaningful
(falls back to `ServerSettings.default_module_entitlement_policy` for
entitlement, or the registry's own `ModuleDefinition.default_enabled` for
enablement — see `app.modules.registry`'s `is_module_entitled`/
`is_module_enabled`), so this migration adds no backfill, matching 0023's
own "additive columns/tables only" precedent.
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
