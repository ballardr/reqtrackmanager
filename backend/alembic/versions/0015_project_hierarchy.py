"""Project hierarchy

Revision ID: 0015
Revises: 0014
Create Date: 2026-08-26

Adds hierarchical (parent/child) projects: an unlimited-depth tree through `projects.parent_project_id`,
a configurable forward (parent -> child) RBAC-cascade mode (`role_inheritance_mode` /
`role_inheritance_filter_role`), a parent-owned "consume members from this child" list
(`project_member_sources`), the `parent_required` bypass guard on relaxed child creation, and the
org-level toggle `organizations.allow_relaxed_child_project_creation`. The reverse mechanism is a
parent-owned list authorised by `require_project_manage` on the parent, so a child manager cannot grant
the child's members read access to a confidential parent (docs/decisions.md, "Hierarchical projects").

New columns are nullable or default to plain roots with no inheritance and the new table starts empty,
so existing data needs no backfill.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE projects ADD COLUMN IF NOT EXISTS parent_project_id UUID "
        "REFERENCES projects(id) ON DELETE SET NULL"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_projects_parent_project_id ON projects (parent_project_id)")
    op.execute(
        "ALTER TABLE projects ADD COLUMN IF NOT EXISTS role_inheritance_mode VARCHAR(20) "
        "NOT NULL DEFAULT 'none'"
    )
    op.execute("ALTER TABLE projects ADD COLUMN IF NOT EXISTS role_inheritance_filter_role VARCHAR(30)")
    op.execute("ALTER TABLE projects ADD COLUMN IF NOT EXISTS parent_required BOOLEAN NOT NULL DEFAULT false")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS project_member_sources (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            source_project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            UNIQUE (project_id, source_project_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_project_member_sources_project_id "
        "ON project_member_sources (project_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_project_member_sources_source_project_id "
        "ON project_member_sources (source_project_id)"
    )

    op.execute(
        "ALTER TABLE organizations ADD COLUMN IF NOT EXISTS allow_relaxed_child_project_creation "
        "BOOLEAN NOT NULL DEFAULT true"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE organizations DROP COLUMN IF EXISTS allow_relaxed_child_project_creation")
    op.execute("DROP TABLE IF EXISTS project_member_sources")
    op.execute("ALTER TABLE projects DROP COLUMN IF EXISTS parent_required")
    op.execute("ALTER TABLE projects DROP COLUMN IF EXISTS role_inheritance_filter_role")
    op.execute("ALTER TABLE projects DROP COLUMN IF EXISTS role_inheritance_mode")
    op.execute("DROP INDEX IF EXISTS ix_projects_parent_project_id")
    op.execute("ALTER TABLE projects DROP COLUMN IF EXISTS parent_project_id")
