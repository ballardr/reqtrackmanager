"""Direct org-group project role grants

Revision ID: 0021
Revises: 0020
Create Date: 2026-09-01

Adds the `org_group_project_roles` table: an organisation group holds a project role directly, as its
own independently revocable record, parallel to `user_project_roles` (`app.models.project.OrgGroupProjectRole`).
It is additive to nesting (`ProjectGroupMember.org_group_id`, C-U-12), which bundles several groups and
users under one named role (docs/decisions.md's identify/verify/remediate entry for this change).

The table starts empty; no backfill.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS org_group_project_roles (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            org_group_id UUID NOT NULL REFERENCES org_groups(id) ON DELETE CASCADE,
            project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            role VARCHAR(30) NOT NULL,
            UNIQUE (org_group_id, project_id, role)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_org_group_project_roles_org_group_id "
        "ON org_group_project_roles (org_group_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_org_group_project_roles_project_id "
        "ON org_group_project_roles (project_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS org_group_project_roles")
