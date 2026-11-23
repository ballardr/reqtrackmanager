"""Standard-scoped RBAC: standards_manager/standards_contributor

Revision ID: 0035
Revises: 0034
Create Date: 2026-09-09

Adds `compliance_org_settings` (`ComplianceOrgSettings`), the module's organisation-level settings table, holding the
organisation's default compliance-managers group: the fallback that keeps a standard from having no `standards_manager`
(§3). See that model for why it is a module-owned table rather than an `Organization` column.

The `standards_manager` and `standards_contributor` roles need no schema beyond the core `user_module_roles.
scope_entity_id` column (core migration 0034): a grant is a `UserModuleRole` row whose `scope_entity_id` is the
standard's id.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0035"
down_revision: str | None = "0034"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS compliance_org_settings (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            default_standards_manager_group_id UUID REFERENCES org_groups(id) ON DELETE SET NULL,
            UNIQUE (organization_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_compliance_org_settings_organization_id "
        "ON compliance_org_settings (organization_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS compliance_org_settings")
