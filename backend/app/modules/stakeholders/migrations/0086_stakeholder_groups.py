"""Stakeholder groups

Revision ID: 0086
Revises: 0085
Create Date: 2026-10-13

Adds `stakeholder_groups`, a tree of org- or project-scoped groups that
classify stakeholders, and `stakeholder_group_members`, the many-to-many direct
memberships. Nothing is backfilled: the "create groups from Organisation /
group text" action proposes groups on request instead.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0086"
down_revision: str | None = "0085"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS stakeholder_groups (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            scope VARCHAR(20) NOT NULL,
            organization_id UUID REFERENCES organizations(id) ON DELETE CASCADE,
            project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
            parent_group_id UUID REFERENCES stakeholder_groups(id) ON DELETE SET NULL,
            name VARCHAR(200) NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            exclusive_children BOOLEAN NOT NULL DEFAULT false,
            sort_order INTEGER NOT NULL DEFAULT 0,
            CONSTRAINT ck_stakeholder_groups_scope_matches_owner CHECK (
                (scope = 'organization' AND organization_id IS NOT NULL AND project_id IS NULL) OR
                (scope = 'project' AND project_id IS NOT NULL AND organization_id IS NULL)
            ),
            CONSTRAINT ck_stakeholder_groups_not_own_parent CHECK (parent_group_id IS NULL OR parent_group_id <> id)
        )
        """
    )
    for column in ("organization_id", "project_id", "parent_group_id"):
        op.execute(f"CREATE INDEX IF NOT EXISTS ix_stakeholder_groups_{column} ON stakeholder_groups ({column})")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS stakeholder_group_members (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            group_id UUID NOT NULL REFERENCES stakeholder_groups(id) ON DELETE CASCADE,
            stakeholder_id UUID NOT NULL REFERENCES stakeholders(id) ON DELETE CASCADE,
            CONSTRAINT uq_stakeholder_group_members_pair UNIQUE (group_id, stakeholder_id)
        )
        """
    )
    for column in ("group_id", "stakeholder_id"):
        op.execute(
            f"CREATE INDEX IF NOT EXISTS ix_stakeholder_group_members_{column} ON stakeholder_group_members ({column})"
        )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS stakeholder_group_members")
    op.execute("DROP TABLE IF EXISTS stakeholder_groups")
