"""Fine-Grained Access Control: custom role data model

Revision ID: 0046
Revises: 0045
Create Date: 2026-09-23

`docs/plans/core-fine-grained-access-control-plan.md` Phase 1: four new
tables backing an organisation-definable custom role, additive to the
fixed `OrgRole`/`ProjectRole` enums and every module-contributed role
(never a replacement — Design Principle 1 of that plan).

- `custom_role_definitions` (`app.models.custom_role.CustomRoleDefinition`)
  — one row per org-defined role: name/description/scope, org-scoped,
  unique per `(organization_id, name)`.
- `custom_role_permissions` (`CustomRolePermission`) — the role's
  permission-atom membership, one row per atom (a normalised join table,
  not a serialized array — same precedent `artefact_links` already set for
  a per-row-queryable set), unique per `(custom_role_id, permission)`.
- `user_custom_role_grants` / `group_custom_role_grants`
  (`UserCustomRoleGrant`/`GroupCustomRoleGrant`) — grants a role to a user
  or an org group, structurally identical to the existing `user_module_
  roles`/`group_module_roles` pair (0025/0037) one tier down (a custom role
  instead of a module-contributed one).

Every table is a brand-new, initially-empty table — no backfill needed.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0046"
down_revision: str | None = "0045"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS custom_role_definitions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            name VARCHAR(100) NOT NULL,
            description TEXT NOT NULL,
            scope VARCHAR(20) NOT NULL,
            created_by UUID REFERENCES users(id),
            UNIQUE (organization_id, name)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_custom_role_definitions_organization_id "
        "ON custom_role_definitions (organization_id)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS custom_role_permissions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            custom_role_id UUID NOT NULL REFERENCES custom_role_definitions(id) ON DELETE CASCADE,
            permission VARCHAR(200) NOT NULL,
            UNIQUE (custom_role_id, permission)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_custom_role_permissions_custom_role_id "
        "ON custom_role_permissions (custom_role_id)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS user_custom_role_grants (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            custom_role_id UUID NOT NULL REFERENCES custom_role_definitions(id) ON DELETE CASCADE,
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
            granted_by UUID REFERENCES users(id),
            UNIQUE (user_id, custom_role_id, project_id)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_user_custom_role_grants_user_id ON user_custom_role_grants (user_id)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_user_custom_role_grants_custom_role_id "
        "ON user_custom_role_grants (custom_role_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_user_custom_role_grants_organization_id "
        "ON user_custom_role_grants (organization_id)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS group_custom_role_grants (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            org_group_id UUID NOT NULL REFERENCES org_groups(id) ON DELETE CASCADE,
            custom_role_id UUID NOT NULL REFERENCES custom_role_definitions(id) ON DELETE CASCADE,
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
            granted_by UUID REFERENCES users(id),
            UNIQUE (org_group_id, custom_role_id, project_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_group_custom_role_grants_org_group_id "
        "ON group_custom_role_grants (org_group_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_group_custom_role_grants_custom_role_id "
        "ON group_custom_role_grants (custom_role_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_group_custom_role_grants_organization_id "
        "ON group_custom_role_grants (organization_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS group_custom_role_grants")
    op.execute("DROP TABLE IF EXISTS user_custom_role_grants")
    op.execute("DROP TABLE IF EXISTS custom_role_permissions")
    op.execute("DROP TABLE IF EXISTS custom_role_definitions")
