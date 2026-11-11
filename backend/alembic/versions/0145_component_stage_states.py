"""Component phases

Revision ID: 0145
Revises: 0144
Create Date: 2026-11-07

Adds `component_stage_states` (a component's workflow position within one project stage), the nullable
`projects.component_phases_mode` switch (NULL inherits, else off) and `baselines.component_id` (set on a baseline
written for one component). Nothing is seeded or backfilled: with the switch unset every project behaves as before.
Guarded so a database built from the current models passes.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0145"
down_revision: str | None = "0144"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE projects ADD COLUMN IF NOT EXISTS component_phases_mode VARCHAR(3)")
    op.execute(
        "ALTER TABLE baselines ADD COLUMN IF NOT EXISTS component_id UUID REFERENCES project_components(id) ON DELETE CASCADE"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS component_stage_states (
            id UUID PRIMARY KEY,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            component_id UUID NOT NULL REFERENCES project_components(id) ON DELETE CASCADE,
            stage_id UUID NOT NULL REFERENCES project_stages(id) ON DELETE CASCADE,
            workflow_id UUID NOT NULL REFERENCES stage_workflows(id),
            phase_id UUID NOT NULL REFERENCES stage_workflow_phases(id),
            not_applicable BOOLEAN NOT NULL DEFAULT FALSE,
            owner_type VARCHAR(20),
            owner_id UUID,
            approved_at TIMESTAMPTZ,
            approved_by UUID REFERENCES users(id),
            completed_at TIMESTAMPTZ,
            completed_by UUID REFERENCES users(id),
            UNIQUE (component_id, stage_id),
            CONSTRAINT ck_owner_principal CHECK (
                (owner_type IS NULL OR owner_type IN ('user', 'org_group', 'project_group'))
                AND ((owner_type IS NULL) = (owner_id IS NULL))
            )
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_component_stage_states_project_id ON component_stage_states (project_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_component_stage_states_stage_id ON component_stage_states (stage_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_component_stage_states_workflow_id ON component_stage_states (workflow_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_component_stage_states_phase_id ON component_stage_states (phase_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS component_stage_states")
    op.execute("ALTER TABLE baselines DROP COLUMN IF EXISTS component_id")
    op.execute("ALTER TABLE projects DROP COLUMN IF EXISTS component_phases_mode")
