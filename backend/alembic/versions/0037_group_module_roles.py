"""Group-based grants for module-contributed roles

Revision ID: 0037
Revises: 0036
Create Date: 2026-09-09

Adds `group_module_roles` (`app.models.module_role.GroupModuleRole`), the group-level counterpart to
`user_module_roles`, so every module-contributed role can be granted to an organisation group (**Decided
by: User**). It is a core, module-generic table (`app.models.module_role`, `app.services.rbac`); as in
0034, it sits in the core chain and continues the Compliance module's 0036 in the merged chain
`app.modules.registry.configure_alembic_version_locations` builds.

Structurally identical to `user_module_roles` (0025) plus its `scope_entity_id` (0034), with
`org_group_id` (FK `org_groups.id`, CASCADE, indexed) in place of `user_id`. The table starts empty; no
backfill.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0037"
down_revision: str | None = "0036"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS group_module_roles (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            org_group_id UUID NOT NULL REFERENCES org_groups(id) ON DELETE CASCADE,
            module_key VARCHAR(100) NOT NULL,
            role_key VARCHAR(100) NOT NULL,
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
            granted_by UUID REFERENCES users(id),
            scope_entity_id UUID,
            UNIQUE (org_group_id, module_key, role_key, organization_id, project_id, scope_entity_id)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_group_module_roles_org_group_id ON group_module_roles (org_group_id)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_group_module_roles_organization_id ON group_module_roles (organization_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_group_module_roles_scope_entity_id ON group_module_roles (scope_entity_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS group_module_roles")
