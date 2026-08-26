"""Project hierarchy

Revision ID: 0015
Revises: 0014
Create Date: 2026-08-26

Adds hierarchical (parent/child) project support: an unlimited-depth tree
via `projects.parent_project_id`, a configurable forward (parent -> child)
RBAC-cascade mode (`role_inheritance_mode` / `role_inheritance_filter_role`),
a parent-owned "consume members from this child" list
(`project_member_sources`, the reverse child -> parent mechanism), the
`parent_required` bypass guard on relaxed child creation, and an org-level
toggle (`organizations.allow_relaxed_child_project_creation`) for that
relaxed path. See docs/decisions.md's "Hierarchical projects" entry for the
full design rationale, including a security correction made during planning:
the reverse mechanism was originally drafted as a boolean on the child,
gated by the child's own manage rights, which allowed a low-privileged
child manager to grant that child's members read access into a confidential
parent without the parent's consent — replaced with this parent-owned list,
authorized only by `require_project_manage` on the parent.

Every new column is nullable or has a default that makes existing projects
plain roots with no inheritance in either direction, and the new table
starts empty — a pure no-op on existing data, no backfill needed.
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
