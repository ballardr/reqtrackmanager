"""Group-based grants for module-contributed roles (module system Phase 30)

Revision ID: 0037
Revises: 0036
Create Date: 2026-09-09

Adds `group_module_roles` (`app.models.module_role.GroupModuleRole`) — the
group-level counterpart to `user_module_roles`, reversing that table's own
originally-documented "direct grants only" boundary (module system Phase 2)
per docs/compliance-module-plan.md Phase 30 — **Decided by: User**, not an
implementation-driven scope change: a human-review round of the Standards
Manager/Contributor picker (Phase 22) found the exclusion undesirable, and
this closes it generically for every module-contributed role, not just
Compliance's own.

This is a core, module-system-generic table (`app.models.module_role`,
`app.services.rbac`), not a compliance-specific one — same "lives in the
core Alembic chain even though compliance's own migrations directory sits
between the two nearest core revisions" situation 0034's own docstring
already explains, since this revision continues on from the Compliance
module's own most recent migration (0036) in the single merged chain
`app.modules.registry.configure_alembic_version_locations` builds.

Structurally identical to `user_module_roles` (0025) plus its
`scope_entity_id` widening (0034), with `org_group_id` (FK `org_groups.id`,
CASCADE, indexed) in place of `user_id`. No backfill needed — this is a
brand-new, initially-empty table.
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
