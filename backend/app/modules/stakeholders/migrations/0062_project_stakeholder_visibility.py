"""Project stakeholder visibility overrides (Module 2 Phase 3b)

Revision ID: 0062
Revises: 0061
Create Date: 2026-10-05

Adds `project_stakeholder_visibility`: a project's override-only record of
whether one org Stakeholder is hidden from it (docs/plans/module-02-
stakeholders-and-personas-plan.md Phase 3b). No row means "inherit from the
nearest ancestor project, else visible".
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0062"
down_revision: str | None = "0061"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS project_stakeholder_visibility (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            stakeholder_id UUID NOT NULL REFERENCES stakeholders(id) ON DELETE CASCADE,
            hidden BOOLEAN NOT NULL,
            CONSTRAINT uq_project_stakeholder_visibility_project_stakeholder UNIQUE (project_id, stakeholder_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_project_stakeholder_visibility_project_id "
        "ON project_stakeholder_visibility (project_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS project_stakeholder_visibility")
