"""Module-contributed RBAC: generalised entity scope (module system Phase 22)

Revision ID: 0034
Revises: 0033
Create Date: 2026-09-09

Adds `user_module_roles.scope_entity_id` (`app.models.module_role.
UserModuleRole`) — the generalised sibling of `project_id` for a
module-owned entity scope (any `ModuleRoleDefinition.scope` value other
than the two core-recognised `"org"`/`"project"` literals), added by
docs/compliance-module-plan.md Phase 22 so compliance's own new
per-`ComplianceStandard` `standards_manager`/`standards_contributor` roles
(and any future module's own first-class-entity role) don't need a
bespoke grant table of their own. This is a core, module-system-generic
change (`app.models.module_role`, `app.services.rbac`), not a
compliance-specific one — see that phase's own notes in
docs/compliance-module-plan.md for why it lives in the core Alembic chain
(`backend/alembic/versions/`) rather than the Compliance module's own
`app/modules/compliance/migrations/` directory, even though this revision
number continues directly on from that module's own most recent one
(0033) in the single merged chain `app.modules.registry.
configure_alembic_version_locations` builds.

Deliberately a bare, un-indexed-by-FK `UUID` column (nullable, `NULL` for
every existing `"org"`/`"project"` grant) — like `module_key`/`role_key`,
this column records a grant against a scope whose meaning (which table it
points into) is owned by the declaring module, not this core table; see
`UserModuleRole.scope_entity_id`'s own docstring. The existing unique
constraint is widened to include it, matching how `project_id` was already
included, even though (per that constraint's own pre-existing docstring
note) Postgres's NULL-distinctness means it remains a backstop, not the
actual dedup mechanism — app-level existing-row checks still do that work,
unchanged.

No backfill needed: every existing `user_module_roles` row is `"org"`- or
`"project"`-scoped and gets `scope_entity_id = NULL`, which is exactly
what those scopes' resolution path already expects.
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
    # Drop the old 5-part unique constraint 0025 created with no explicit
    # name (Postgres auto-generates one, which can be silently truncated —
    # located by column membership rather than a guessed literal name, the
    # same precedent 0012's own migration already set for this exact
    # situation; see that revision's module docstring).
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
