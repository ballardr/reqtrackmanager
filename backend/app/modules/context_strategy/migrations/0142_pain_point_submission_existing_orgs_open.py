"""Existing organisations keep Pain Point submission open to members

Revision ID: 0142
Revises: 0141
Create Date: 2026-11-07

The platform default for who may submit a Pain Point is Pain Point Managers only. Organisations that already
exist submitted as any project member, so each gets an explicit organisation default of `members` and none loses
the ability on upgrade. An organisation that already has a default is left alone. Organisations created later
follow the platform default.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0142"
down_revision: str | None = "0141"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO pain_point_submission_settings (id, created_at, updated_at, organization_id, project_id, policy)
        SELECT gen_random_uuid(), now(), now(), o.id, NULL, 'members'
        FROM organizations o
        WHERE NOT EXISTS (
            SELECT 1 FROM pain_point_submission_settings s
            WHERE s.organization_id = o.id AND s.project_id IS NULL
        )
        """
    )


def downgrade() -> None:
    # The rows are indistinguishable from ones an administrator chose, so none are removed.
    pass
