"""Fine-Grained Access Control: custom-role entity-scoped grants

Revision ID: 0047
Revises: 0046
Create Date: 2026-09-27

`docs/plans/core-fine-grained-access-control-plan.md` Phase 5: adds
`scope_entity_id` to `user_custom_role_grants`/`group_custom_role_grants`
(`app.models.custom_role.UserCustomRoleGrant`/`GroupCustomRoleGrant`) — the
generalised sibling of `project_id`, for a `CustomRoleDefinition` whose
`scope` is a registered module-owned entity scope (Phase 5's new
`EntityScopeDefinition` registry, e.g. compliance's `"standard"`) rather
than `"org"`/`"project"`. Mirrors `0034_module_role_scope_entity.py`'s
identical addition to `user_module_roles` one tier up (a module-contributed
role instead of a custom one) field-for-field: a bare, un-indexed-by-FK
`UUID` column (nullable, `NULL` for every existing `"org"`/`"project"`
grant), since the column records a grant against a scope whose meaning is
owned by the declaring module, not this core table.

Both tables' existing 3-part unique constraints (`0046`, created with no
explicit name) are widened to include the new column, matching how
`0034` widened `user_module_roles`'s own constraint — located by column
membership rather than a guessed auto-generated name, the same defensive
precedent `0034` and `0012` already set.

No backfill needed: every existing row is `"org"`- or `"project"`-scoped
and gets `scope_entity_id = NULL`, which is exactly what those scopes'
resolution path already expects.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0047"
down_revision: str | None = "0046"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE user_custom_role_grants ADD COLUMN IF NOT EXISTS scope_entity_id UUID")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_user_custom_role_grants_scope_entity_id "
        "ON user_custom_role_grants (scope_entity_id)"
    )
    op.execute("ALTER TABLE group_custom_role_grants ADD COLUMN IF NOT EXISTS scope_entity_id UUID")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_group_custom_role_grants_scope_entity_id "
        "ON group_custom_role_grants (scope_entity_id)"
    )

    _replace_unique_constraint(
        table="user_custom_role_grants",
        new_name="uq_user_custom_role_grants_scope",
        new_columns="user_id, custom_role_id, project_id, scope_entity_id",
        old_column_count=3,
        distinguishing_column="custom_role_id",
    )
    _replace_unique_constraint(
        table="group_custom_role_grants",
        new_name="uq_group_custom_role_grants_scope",
        new_columns="org_group_id, custom_role_id, project_id, scope_entity_id",
        old_column_count=3,
        distinguishing_column="custom_role_id",
    )


def _replace_unique_constraint(
    *, table: str, new_name: str, new_columns: str, old_column_count: int, distinguishing_column: str
) -> None:
    op.execute(
        f"""
        DO $$
        DECLARE
            old_constraint RECORD;
        BEGIN
            FOR old_constraint IN
                SELECT con.conname
                FROM pg_constraint con
                JOIN pg_class rel ON rel.oid = con.conrelid
                WHERE rel.relname = '{table}'
                  AND con.contype = 'u'
                  AND con.conname != '{new_name}'
                  AND array_length(con.conkey, 1) = {old_column_count}
                  AND EXISTS (
                      SELECT 1 FROM unnest(con.conkey) AS colnum
                      JOIN pg_attribute att ON att.attrelid = con.conrelid AND att.attnum = colnum
                      WHERE att.attname = '{distinguishing_column}'
                  )
            LOOP
                EXECUTE 'ALTER TABLE {table} DROP CONSTRAINT ' || quote_ident(old_constraint.conname);
            END LOOP;
        END $$;
        """
    )
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = '{new_name}') THEN
                ALTER TABLE {table} ADD CONSTRAINT {new_name} UNIQUE ({new_columns});
            END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE user_custom_role_grants DROP CONSTRAINT IF EXISTS uq_user_custom_role_grants_scope")
    op.execute(
        "ALTER TABLE user_custom_role_grants ADD CONSTRAINT uq_user_custom_role_grants_pre_phase5 "
        "UNIQUE (user_id, custom_role_id, project_id)"
    )
    op.execute("DROP INDEX IF EXISTS ix_user_custom_role_grants_scope_entity_id")
    op.execute("ALTER TABLE user_custom_role_grants DROP COLUMN IF EXISTS scope_entity_id")

    op.execute("ALTER TABLE group_custom_role_grants DROP CONSTRAINT IF EXISTS uq_group_custom_role_grants_scope")
    op.execute(
        "ALTER TABLE group_custom_role_grants ADD CONSTRAINT uq_group_custom_role_grants_pre_phase5 "
        "UNIQUE (org_group_id, custom_role_id, project_id)"
    )
    op.execute("DROP INDEX IF EXISTS ix_group_custom_role_grants_scope_entity_id")
    op.execute("ALTER TABLE group_custom_role_grants DROP COLUMN IF EXISTS scope_entity_id")
