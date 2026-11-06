"""Pain Point submission settings

Revision ID: 0141
Revises: 0140
Create Date: 2026-11-07

Adds `pain_point_submission_settings`: who may submit a Pain Point, one optional row per project and one
per organisation (the default; `project_id` NULL). Absence means "inherit" and, at the end of the chain,
any project member, so existing projects behave as before.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0141"
down_revision: str | None = "0140"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS pain_point_submission_settings (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
            policy VARCHAR(20) NOT NULL
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_pain_point_submission_settings_org "
        "ON pain_point_submission_settings (organization_id) WHERE project_id IS NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_pain_point_submission_settings_project "
        "ON pain_point_submission_settings (project_id) WHERE project_id IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS pain_point_submission_settings")
