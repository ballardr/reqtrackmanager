"""Project visibility

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-16

Adds `projects.visibility` (`ProjectVisibility`: "only_specified" default, or "org_wide", which gives
every member of the project's organisation baseline view access; see
`app/services/rbac.py::get_effective_project_roles`).

`IF NOT EXISTS`, as in 0002.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE projects ADD COLUMN IF NOT EXISTS visibility VARCHAR(20) NOT NULL DEFAULT 'only_specified'"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE projects DROP COLUMN IF EXISTS visibility")
