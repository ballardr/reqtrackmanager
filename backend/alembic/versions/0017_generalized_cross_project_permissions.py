"""Generalized cross-project group permissions

Revision ID: 0017
Revises: 0016
Create Date: 2026-08-28

Two additions to the cross-project RBAC model, both requested directly (see
docs/decisions.md's entry on this migration for the full identify->verify->
remediate security review):

1. `project_member_sources` gains `mirror_mode`/`mirror_filter_role`, and
   its `source_project_id` is no longer required to be a direct child of
   the owning project (that constraint lives in application code —
   `services.rbac`/`routers.projects` — not the database; see
   `models.project.ProjectMemberSource`'s docstring). Existing rows are
   backfilled to `mirror_mode = 'member_only'`, which reproduces their
   original MEMBER-only behavior exactly.
2. `project_group_members` gains `source_project_id` ("this group's
   members = that project's own direct members"), and its two-way
   "exactly one of user_id/org_group_id" check constraint becomes
   three-way. Existing rows are unaffected (`source_project_id` is NULL for
   all of them, same as before this column existed).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE project_member_sources ADD COLUMN IF NOT EXISTS mirror_mode VARCHAR(20) "
        "NOT NULL DEFAULT 'member_only'"
    )
    op.execute("ALTER TABLE project_member_sources ADD COLUMN IF NOT EXISTS mirror_filter_role VARCHAR(30)")

    op.execute(
        "ALTER TABLE project_group_members ADD COLUMN IF NOT EXISTS source_project_id UUID "
        "REFERENCES projects(id) ON DELETE CASCADE"
    )
    op.execute(
        "ALTER TABLE project_group_members DROP CONSTRAINT IF EXISTS ck_project_group_member_exactly_one_target"
    )
    op.execute(
        """
        ALTER TABLE project_group_members ADD CONSTRAINT ck_project_group_member_exactly_one_target
        CHECK (
            (user_id IS NOT NULL)::int + (org_group_id IS NOT NULL)::int + (source_project_id IS NOT NULL)::int = 1
        )
        """
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE project_group_members DROP CONSTRAINT IF EXISTS ck_project_group_member_exactly_one_target"
    )
    op.execute(
        """
        ALTER TABLE project_group_members ADD CONSTRAINT ck_project_group_member_exactly_one_target
        CHECK ((user_id IS NOT NULL)::int + (org_group_id IS NOT NULL)::int = 1)
        """
    )
    op.execute("ALTER TABLE project_group_members DROP COLUMN IF EXISTS source_project_id")
    op.execute("ALTER TABLE project_member_sources DROP COLUMN IF EXISTS mirror_filter_role")
    op.execute("ALTER TABLE project_member_sources DROP COLUMN IF EXISTS mirror_mode")
