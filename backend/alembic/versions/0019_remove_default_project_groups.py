"""Remove default project groups; migrate to direct role grants

Revision ID: 0019
Revises: 0018
Create Date: 2026-08-31

`create_project` no longer creates four standard `ProjectGroup` rows per project (`is_default=True`:
"Project Managers"/"Project Administrators"/"Stakeholders"/"Members", `DEFAULT_GROUPS` in
`routers/projects.py`); it grants the creator's initial `PROJECT_MANAGER` role directly through a
`UserProjectRole`. `is_default` is removed from the schema, so no group is protected from deletion; only
the C-U-08 guard (a project always retains at least one manager) remains (docs/decisions.md).

For every `project_groups` row with `is_default = true`:
  1. Each direct user member (`project_group_members.user_id IS NOT NULL`) becomes a direct
     `user_project_roles` grant with the group's `role` (`ON CONFLICT ... DO NOTHING` on the
     `(user_id, project_id, role)` unique constraint, so an existing identical grant is not duplicated).
  2. A group with only plain direct user members (no `org_group_id`, no `source_project_id`) is deleted;
     its `project_group_members` rows go with it through `ON DELETE CASCADE`.
  3. A group with other composition (for example a `source_project_id` reference) is kept with
     `is_default` set to `false`, because a `UserProjectRole` cannot represent that composition. Its
     direct members also hold the role directly, which is redundant but equivalent.

C-U-08 holds by construction: every direct member of a manager-role default group keeps that role
directly, and a group is deleted only after its direct members are carried forward.
`backend/tests/test_default_group_migration.py` pins both branches.

Guarded by `IF EXISTS (... information_schema.columns ...)`, as in 0014/0017/0018: the current models
define no `is_default`, so a fresh database never has the column and the backfill is a no-op.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        DECLARE
            grp RECORD;
            has_extra_composition BOOLEAN;
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'project_groups' AND column_name = 'is_default'
            ) THEN
                FOR grp IN SELECT id, project_id, role FROM project_groups WHERE is_default = true
                LOOP
                    -- Materialize every direct user member into a direct
                    -- grant first, regardless of which branch this group
                    -- ends up taking below.
                    INSERT INTO user_project_roles (id, user_id, project_id, role, created_at, updated_at)
                    SELECT gen_random_uuid(), pgm.user_id, grp.project_id, grp.role, now(), now()
                    FROM project_group_members pgm
                    WHERE pgm.project_group_id = grp.id AND pgm.user_id IS NOT NULL
                    ON CONFLICT (user_id, project_id, role) DO NOTHING;

                    SELECT EXISTS (
                        SELECT 1 FROM project_group_members pgm
                        WHERE pgm.project_group_id = grp.id
                          AND (pgm.org_group_id IS NOT NULL OR pgm.source_project_id IS NOT NULL)
                    ) INTO has_extra_composition;

                    IF has_extra_composition THEN
                        -- Keeps its nested composition; no longer specially
                        -- protected — an ordinary custom group from here on.
                        UPDATE project_groups SET is_default = false WHERE id = grp.id;
                    ELSE
                        -- Fully materialized and nothing else to lose —
                        -- project_group_members rows cascade with it.
                        DELETE FROM project_groups WHERE id = grp.id;
                    END IF;
                END LOOP;
            END IF;
        END $$;
        """
    )

    op.execute("ALTER TABLE project_groups DROP COLUMN IF EXISTS is_default")


def downgrade() -> None:
    # Lossy, as in 0018's downgrade: once some default groups are deleted and the rest demoted, nothing
    # distinguishes a migrated former default group from a custom one. The column is restored with every
    # existing group set to `false`.
    op.execute("ALTER TABLE project_groups ADD COLUMN IF NOT EXISTS is_default BOOLEAN NOT NULL DEFAULT false")
