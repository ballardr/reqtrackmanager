"""Project can_be_parent eligibility gate

Revision ID: 0016
Revises: 0015
Create Date: 2026-08-26

Adds `projects.can_be_parent`, a manager-controlled gate (default `False`) on whether a project may be
selected as the parent of other projects; `routers.projects.create_project`/`update_project` return 400
when the intended parent has it `False` (docs/decisions.md, "Hierarchical projects"). The opt-in keeps
the "Parent project" picker limited to eligible projects and requires the parent's own manager to agree.

Projects that already have a child are backfilled to `can_be_parent = true`, so existing hierarchies
are unaffected and only new attachments are gated.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE projects ADD COLUMN IF NOT EXISTS can_be_parent BOOLEAN NOT NULL DEFAULT false")
    op.execute(
        """
        UPDATE projects SET can_be_parent = true
        WHERE id IN (SELECT DISTINCT parent_project_id FROM projects WHERE parent_project_id IS NOT NULL)
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE projects DROP COLUMN IF EXISTS can_be_parent")
