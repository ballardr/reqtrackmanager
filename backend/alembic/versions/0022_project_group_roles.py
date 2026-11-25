"""Project group roles become independent grants

Revision ID: 0022
Revises: 0021
Create Date: 2026-09-01

A `ProjectGroup` carries a set of roles instead of one required `role` column
(`app.models.project.ProjectGroupRole`; docs/decisions.md, members/groups directory). A group can hold
zero, one or several independently revocable roles, one `project_group_roles` row per role, the same
shape as `user_project_roles`/`org_group_project_roles`. The old column is backfilled and dropped in
this one migration, so no revision holds both shapes.

Backfill: every `project_groups` row gets one `project_group_roles` row with its current `role`;
`ON CONFLICT (project_group_id, role) DO NOTHING` makes a re-run safe.

Guarded by `IF EXISTS (... information_schema.columns ...)`, as in 0014/0017/0018/0019: the current
models define no `ProjectGroup.role`, so a fresh database never has the column and the backfill is a no-op.

Every C-U-08 guard (a project retains at least one manager: `_ensure_project_has_a_manager`,
`delete_project_group`, `remove_project_group_member`, the group-role-revoke endpoint) checks whether
the group holds a `PROJECT_MANAGER` row in the new table (docs/decisions.md's identify/verify/remediate
entry for this change).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS project_group_roles (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            project_group_id UUID NOT NULL REFERENCES project_groups(id) ON DELETE CASCADE,
            role VARCHAR(30) NOT NULL,
            UNIQUE (project_group_id, role)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_project_group_roles_project_group_id "
        "ON project_group_roles (project_group_id)"
    )

    # Backfill — see module docstring. Only runs against a database that
    # still has `project_groups.role` (i.e. one migrated from before this
    # revision); a fresh database's models never define that column.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'project_groups' AND column_name = 'role'
            ) THEN
                INSERT INTO project_group_roles (id, project_group_id, role, created_at, updated_at)
                SELECT gen_random_uuid(), pg.id, pg.role, now(), now()
                FROM project_groups pg
                ON CONFLICT (project_group_id, role) DO NOTHING;
            END IF;
        END $$;
        """
    )

    op.execute("ALTER TABLE project_groups DROP COLUMN IF EXISTS role")


def downgrade() -> None:
    # Lossy for a group with more than one role (a scalar column cannot hold two), as in 0019's downgrade.
    # It keeps the highest-privilege role (project_manager > project_administrator > stakeholder > member)
    # so a downgrade never lowers a manager grant; a group with no roles becomes 'member', the old
    # required-field default.
    op.execute("ALTER TABLE project_groups ADD COLUMN IF NOT EXISTS role VARCHAR(30)")
    op.execute(
        """
        DO $$
        DECLARE
            g RECORD;
        BEGIN
            FOR g IN
                SELECT DISTINCT project_group_id FROM project_group_roles
                UNION
                SELECT id AS project_group_id FROM project_groups
            LOOP
                UPDATE project_groups SET role = (
                    SELECT pgr.role FROM project_group_roles pgr
                    WHERE pgr.project_group_id = g.project_group_id
                    ORDER BY CASE pgr.role
                        WHEN 'project_manager' THEN 0
                        WHEN 'project_administrator' THEN 1
                        WHEN 'stakeholder' THEN 2
                        ELSE 3
                    END
                    LIMIT 1
                )
                WHERE id = g.project_group_id;
            END LOOP;
        END $$;
        """
    )
    op.execute("UPDATE project_groups SET role = 'member' WHERE role IS NULL")
    op.execute("ALTER TABLE project_groups ALTER COLUMN role SET NOT NULL")
    op.execute("DROP TABLE IF EXISTS project_group_roles")
