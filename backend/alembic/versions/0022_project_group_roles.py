"""Project group roles become independent grants

Revision ID: 0022
Revises: 0021
Create Date: 2026-09-01

Members/groups directory rework plan, PR7 (docs/decisions.md): a
`ProjectGroup` used to carry a single, required `role` column fixed at
creation — a group's role was baked in from the start, with no way to hold
more than one role or start with none. This migration replaces that column
with a new `project_group_roles` table (`app.models.project.
ProjectGroupRole`), mirroring PR4's `org_group_project_roles` table almost
exactly: a group can now hold zero, one, or several independently-revocable
roles, one row per role, the same "one row per role" shape `user_project_
roles`/`org_group_project_roles` already use — not an array/JSON column.

Follows this codebase's own established convention for retiring a
superseded column in one pass (see 0019's `is_default` removal): backfill
first, then drop the column in the same migration, so there is never an
intermediate revision where both the old and new shapes coexist un-
reconciled.

Backfill: for every existing `project_groups` row, insert exactly one
`project_group_roles` row carrying that group's current `role` — no
existing group loses its role in this transition; a group that already
granted `project_manager` keeps that grant (now as its own row) and so on
for every other role. `ON CONFLICT (project_group_id, role) DO NOTHING`
guards against re-running this migration (matching 0019's own idempotency
guard), even though a fresh table can't yet contain a duplicate on first
run.

Guarded by `IF EXISTS (... information_schema.columns ...)` the same way
0014/0017/0018/0019 guard their own backfills: a brand-new database's
`0001_initial.py` already runs `Base.metadata.create_all()` against the
*current* model classes, which no longer define `ProjectGroup.role` at all,
so a fresh database never has the column to begin with and this whole
backfill is a no-op there — only a database migrated from before this
revision has real `role` values to convert.

Every C-U-08 ("a project must retain at least one manager") guard site that
read `ProjectGroup.role == PROJECT_MANAGER` directly (`_ensure_project_has_
a_manager`, `delete_project_group`, `remove_project_group_member`, plus the
new group-role-revoke endpoint) was updated in the same PR to instead check
whether the group currently holds a `PROJECT_MANAGER` row in this new
table — see docs/decisions.md's identify/verify/remediate entry for PR7 for
the full list and review.
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
    # Lossy for any group that ended up with more than one role (there is
    # no way to represent "holds two roles" back in a single scalar column)
    # — same acknowledged lossiness 0019's own downgrade documents for its
    # is_default column. Picks the *highest-privilege* role a group holds
    # (project_manager > project_administrator > stakeholder > member) so a
    # downgrade never silently drops a manager grant down to a lesser role;
    # a group left with zero roles falls back to 'member', matching how a
    # freshly-created (post-PR7) group with no grants yet would have been
    # represented under the old required-field shape.
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
