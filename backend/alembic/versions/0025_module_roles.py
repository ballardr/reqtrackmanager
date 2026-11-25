"""Module-contributed RBAC

Revision ID: 0025
Revises: 0024
Create Date: 2026-09-05

Adds the two tables module-contributed RBAC needs:

- `module_role_definitions` (`app.models.module_role.ModuleRoleDefinitionRow`): a database mirror of
  every role declared in the in-process registry (`app.modules.registry.ModuleRoleDefinition`),
  synchronised at each process startup by `sync_module_role_definitions`. It is append-only (no delete
  path) so a grant's display name and description stay resolvable after the declaring module leaves
  `INSTALLED_MODULES`.
- `user_module_roles` (`app.models.module_role.UserModuleRole`): which user holds which role at which
  scope. Direct grants only, no group or hierarchy inheritance (see the model's docstring).
  `organization_id` is always set (a project-scoped grant uses the project's organisation);
  `project_id` is set only for a project-scoped grant.

No backfill: both tables start empty and the first startup populates `module_role_definitions`.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0025"
down_revision: str | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS module_role_definitions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            module_key VARCHAR(100) NOT NULL,
            role_key VARCHAR(100) NOT NULL,
            name VARCHAR(200) NOT NULL,
            description TEXT NOT NULL,
            scope VARCHAR(20) NOT NULL,
            UNIQUE (module_key, role_key)
        )
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS user_module_roles (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            module_key VARCHAR(100) NOT NULL,
            role_key VARCHAR(100) NOT NULL,
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
            granted_by UUID REFERENCES users(id),
            UNIQUE (user_id, module_key, role_key, organization_id, project_id)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_user_module_roles_user_id ON user_module_roles (user_id)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_user_module_roles_organization_id ON user_module_roles (organization_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS user_module_roles")
    op.execute("DROP TABLE IF EXISTS module_role_definitions")
