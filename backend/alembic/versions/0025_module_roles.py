"""Module-contributed RBAC (module system Phase 2)

Revision ID: 0025
Revises: 0024
Create Date: 2026-09-05

Adds the two tables module-contributed RBAC needs
(docs/compliance-module-plan.md Phase 2), sitting on top of Phase 0's
`server_roles` and Phase 1's `organization_module_entitlements`/
`organization_modules`:

- `module_role_definitions` (`app.models.module_role.
  ModuleRoleDefinitionRow`) — a database mirror of every module-contributed
  role declared by the in-process registry (`app.modules.registry.
  ModuleRoleDefinition`), kept in sync at every process startup by
  `app.modules.registry.sync_module_role_definitions`. Deliberately
  append-only (no delete path exists for it) so a `user_module_roles`
  grant's display name/description stays resolvable even if the declaring
  module is later removed from `INSTALLED_MODULES` — see that model's own
  docstring.
- `user_module_roles` (`app.models.module_role.UserModuleRole`) — the
  grant table itself: which user holds which module-contributed role, at
  which scope. Direct grants only, no group/hierarchy inheritance (a
  deliberate V1 scope boundary — see that model's own docstring).
  `organization_id` is always set (even for a project-scoped grant, via
  the project's own organisation); `project_id` is set only for a
  project-scoped grant.

No backfill of either table — `module_role_definitions` starts empty and
is populated by the next process startup's `sync_module_role_definitions`
call, and `user_module_roles` starts empty since no module with roles is
registered yet (Compliance doesn't land until Phase 5) — matching 0023/
0024's own "additive tables/columns only" precedent.
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
