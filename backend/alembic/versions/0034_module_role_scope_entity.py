"""Module-contributed RBAC: generalised entity scope

Revision ID: 0034
Revises: 0033
Create Date: 2026-09-09

Adds `user_module_roles.scope_entity_id` (`app.models.module_role.UserModuleRole`), the generalised
sibling of `project_id` for a module-owned entity scope (any `ModuleRoleDefinition.scope` other than the
core `"org"`/`"project"` literals). It serves, for example, compliance's per-`ComplianceStandard`
`standards_manager`/`standards_contributor` roles without a bespoke grant table. This is a core,
module-generic change (`app.models.module_role`, `app.services.rbac`); docs/decisions.md explains why it
sits in the core Alembic chain (`backend/alembic/versions/`) rather than the Compliance module's
`app/modules/compliance/migrations/` directory, although the revision number continues that module's
0033 in the merged chain `app.modules.registry.configure_alembic_version_locations` builds.

The column is a nullable `UUID` with no foreign key, `NULL` for every `"org"`/`"project"` grant: which
table it points into is owned by the declaring module (see `UserModuleRole.scope_entity_id`). The unique
constraint is widened to include it; Postgres treats NULLs as distinct, so the constraint is a backstop
and application-level existing-row checks do the deduplication.

No backfill: existing rows are `"org"`- or `"project"`-scoped and get `NULL`.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0034"
down_revision: str | None = "0033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE user_module_roles ADD COLUMN IF NOT EXISTS scope_entity_id UUID")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_user_module_roles_scope_entity_id ON user_module_roles (scope_entity_id)"
    )
    # Drop the old 5-part unique constraint 0025 created without a name, by column membership because
    # Postgres truncates its generated name (see 0012).
    op.execute(
        """
        DO $$
        DECLARE
            old_constraint RECORD;
        BEGIN
            FOR old_constraint IN
                SELECT con.conname
                FROM pg_constraint con
                JOIN pg_class rel ON rel.oid = con.conrelid
                WHERE rel.relname = 'user_module_roles'
                  AND con.contype = 'u'
                  AND con.conname != 'uq_user_module_roles_scope'
                  AND array_length(con.conkey, 1) = 5
                  AND EXISTS (
                      SELECT 1 FROM unnest(con.conkey) AS colnum
                      JOIN pg_attribute att ON att.attrelid = con.conrelid AND att.attnum = colnum
                      WHERE att.attname = 'role_key'
                  )
            LOOP
                EXECUTE 'ALTER TABLE user_module_roles DROP CONSTRAINT ' || quote_ident(old_constraint.conname);
            END LOOP;
        END $$;
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_user_module_roles_scope') THEN
                ALTER TABLE user_module_roles
                ADD CONSTRAINT uq_user_module_roles_scope
                UNIQUE (user_id, module_key, role_key, organization_id, project_id, scope_entity_id);
            END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE user_module_roles DROP CONSTRAINT IF EXISTS uq_user_module_roles_scope")
    op.execute(
        "ALTER TABLE user_module_roles ADD CONSTRAINT uq_user_module_roles_pre_phase22 "
        "UNIQUE (user_id, module_key, role_key, organization_id, project_id)"
    )
    op.execute("DROP INDEX IF EXISTS ix_user_module_roles_scope_entity_id")
    op.execute("ALTER TABLE user_module_roles DROP COLUMN IF EXISTS scope_entity_id")
