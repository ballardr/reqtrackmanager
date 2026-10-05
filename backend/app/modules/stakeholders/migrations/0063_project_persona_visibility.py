"""Project persona visibility overrides (Module 2 Phase 3b, extended to Personas)

Revision ID: 0063
Revises: 0062
Create Date: 2026-10-05

Adds `project_persona_visibility`: a project's override-only record of whether
one org Persona is hidden from it, the Persona counterpart of 0062's
`project_stakeholder_visibility`. No row means "inherit from the nearest
ancestor project, else visible".
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0063"
down_revision: str | None = "0062"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS project_persona_visibility (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            persona_id UUID NOT NULL REFERENCES personas(id) ON DELETE CASCADE,
            hidden BOOLEAN NOT NULL,
            CONSTRAINT uq_project_persona_visibility_project_persona UNIQUE (project_id, persona_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_project_persona_visibility_project_id ON project_persona_visibility (project_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS project_persona_visibility")
