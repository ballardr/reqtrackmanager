"""Standard-scoped RBAC: standards_manager/standards_contributor (Phase 22)

Revision ID: 0035
Revises: 0034
Create Date: 2026-09-09

Adds `compliance_org_settings` (`app.modules.compliance.models.
ComplianceOrgSettings`) — this module's first org-level settings table,
holding (so far) one field: the org's designated default compliance-
managers group, the SSO-friendly fallback that keeps a standard from ever
being left with no `standards_manager` at all (docs/compliance-module-
plan.md Phase 22, §3). See that model's own docstring for the full design
and why this is a module-owned table rather than a new `Organization`
column.

This module's actual new roles (`standards_manager`/`standards_contributor`)
need no schema of their own beyond the core `user_module_roles.
scope_entity_id` column added by the companion core migration (0034,
`backend/alembic/versions/`) — a grant is just an ordinary `UserModuleRole`
row with `scope_entity_id` set to the standard's own id, following exactly
the same "no per-role table" precedent `compliance_manager`/
`compliance_officer` already set.
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
