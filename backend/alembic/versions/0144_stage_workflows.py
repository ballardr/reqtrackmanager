"""Customisable stage workflows

Revision ID: 0144
Revises: 0143
Create Date: 2026-11-07

Adds `stage_workflows` / `stage_workflow_phases` and moves each project stage from the fixed `status` column to a
workflow phase. Every existing organisation gets one organisation-tier workflow, "Standard", whose phases are the
five old states with the kinds that reproduce their behaviour (Scoping open, Review review, Approved locked,
Completed closed, Archived on hold); each stage is pointed at the phase matching its old status, then `status` is
dropped. Guarded so a database built from the current models passes.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0144"
down_revision: str | None = "0143"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PHASES = (
    ("Scoping", "open", 0, "scoping"),
    ("Review", "review", 1, "review"),
    ("Approved", "locked", 2, "approved"),
    ("Completed", "closed", 3, "completed"),
    ("Archived", "on_hold", 4, "archived"),
)


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS stage_workflows (
            id UUID PRIMARY KEY,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
            name VARCHAR(100) NOT NULL,
            sort_order INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_stage_workflows_organization_id ON stage_workflows (organization_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_stage_workflows_project_id ON stage_workflows (project_id)")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_stage_workflows_org_name ON stage_workflows (organization_id, name) "
        "WHERE project_id IS NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_stage_workflows_project_name ON stage_workflows (project_id, name) "
        "WHERE project_id IS NOT NULL"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS stage_workflow_phases (
            id UUID PRIMARY KEY,
            workflow_id UUID NOT NULL REFERENCES stage_workflows(id) ON DELETE CASCADE,
            name VARCHAR(100) NOT NULL,
            kind VARCHAR(20) NOT NULL,
            sort_order INTEGER NOT NULL DEFAULT 0,
            UNIQUE (workflow_id, name)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_stage_workflow_phases_workflow_id ON stage_workflow_phases (workflow_id)")

    op.execute("ALTER TABLE project_stages ADD COLUMN IF NOT EXISTS workflow_id UUID REFERENCES stage_workflows(id)")
    op.execute("ALTER TABLE project_stages ADD COLUMN IF NOT EXISTS phase_id UUID REFERENCES stage_workflow_phases(id)")

    has_status = op.get_bind().exec_driver_sql(
        "SELECT 1 FROM information_schema.columns WHERE table_name = 'project_stages' AND column_name = 'status'"
    ).first()
    if has_status:
        op.execute(
            """
            INSERT INTO stage_workflows (id, created_at, updated_at, organization_id, project_id, name, sort_order)
            SELECT gen_random_uuid(), now(), now(), o.id, NULL, 'Standard', 0
            FROM organizations o
            WHERE NOT EXISTS (
                SELECT 1 FROM stage_workflows w WHERE w.organization_id = o.id AND w.project_id IS NULL AND w.name = 'Standard'
            )
            """
        )
        for name, kind, order, _status in _PHASES:
            op.execute(
                f"""
                INSERT INTO stage_workflow_phases (id, workflow_id, name, kind, sort_order)
                SELECT gen_random_uuid(), w.id, '{name}', '{kind}', {order}
                FROM stage_workflows w
                WHERE w.project_id IS NULL AND w.name = 'Standard'
                  AND NOT EXISTS (SELECT 1 FROM stage_workflow_phases p WHERE p.workflow_id = w.id AND p.name = '{name}')
                """
            )
        for name, _kind, _order, status in _PHASES:
            op.execute(
                f"""
                UPDATE project_stages ps
                SET workflow_id = w.id, phase_id = p.id
                FROM projects pr, stage_workflows w, stage_workflow_phases p
                WHERE ps.status = '{status}' AND ps.phase_id IS NULL
                  AND pr.id = ps.project_id
                  AND w.organization_id = pr.organization_id AND w.project_id IS NULL AND w.name = 'Standard'
                  AND p.workflow_id = w.id AND p.name = '{name}'
                """
            )
        op.execute("ALTER TABLE project_stages DROP COLUMN status")

    op.execute("ALTER TABLE project_stages ALTER COLUMN workflow_id SET NOT NULL")
    op.execute("ALTER TABLE project_stages ALTER COLUMN phase_id SET NOT NULL")
    op.execute("CREATE INDEX IF NOT EXISTS ix_project_stages_workflow_id ON project_stages (workflow_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_project_stages_phase_id ON project_stages (phase_id)")


def downgrade() -> None:
    # Phases carry richer information than the old status; the downgrade is not supported.
    pass
