"""Phase schedule and reminders

Revision ID: 0146
Revises: 0145
Create Date: 2026-11-07

Adds `stage_phase_plans` (expected range and actual dates of a stage's or a component track's phase), the optional
owner on `project_stages` and the nullable `projects.phase_reminder_lead_days`. Nothing is seeded or backfilled: a
stage with no plan rows and no owner is reminded about nothing, as before. Guarded so a database built from the
current models passes.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0146"
down_revision: str | None = "0145"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE projects ADD COLUMN IF NOT EXISTS phase_reminder_lead_days INTEGER")
    op.execute("ALTER TABLE project_stages ADD COLUMN IF NOT EXISTS owner_type VARCHAR(20)")
    op.execute("ALTER TABLE project_stages ADD COLUMN IF NOT EXISTS owner_id UUID")
    op.execute(
        """
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'ck_owner_principal' AND conrelid = 'project_stages'::regclass
            ) THEN
                ALTER TABLE project_stages ADD CONSTRAINT ck_owner_principal CHECK (
                    (owner_type IS NULL OR owner_type IN ('user', 'org_group', 'project_group'))
                    AND ((owner_type IS NULL) = (owner_id IS NULL))
                );
            END IF;
        END $$
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS stage_phase_plans (
            id UUID PRIMARY KEY,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            stage_id UUID NOT NULL REFERENCES project_stages(id) ON DELETE CASCADE,
            component_id UUID REFERENCES project_components(id) ON DELETE CASCADE,
            phase_id UUID NOT NULL REFERENCES stage_workflow_phases(id) ON DELETE CASCADE,
            expected_from DATE,
            expected_to DATE,
            started_at TIMESTAMPTZ,
            completed_at TIMESTAMPTZ,
            upcoming_notified_for DATE,
            overdue_notified_for DATE,
            CONSTRAINT ck_stage_phase_plans_range CHECK (
                expected_from IS NULL OR expected_to IS NULL OR expected_from <= expected_to
            )
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_stage_phase_plans_project_id ON stage_phase_plans (project_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_stage_phase_plans_phase_id ON stage_phase_plans (phase_id)")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_stage_phase_plans_stage ON stage_phase_plans (stage_id, phase_id) "
        "WHERE component_id IS NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_stage_phase_plans_component ON stage_phase_plans (stage_id, component_id, phase_id) "
        "WHERE component_id IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS stage_phase_plans")
    op.execute("ALTER TABLE project_stages DROP CONSTRAINT IF EXISTS ck_owner_principal")
    op.execute("ALTER TABLE project_stages DROP COLUMN IF EXISTS owner_id")
    op.execute("ALTER TABLE project_stages DROP COLUMN IF EXISTS owner_type")
    op.execute("ALTER TABLE projects DROP COLUMN IF EXISTS phase_reminder_lead_days")
