"""Component/category placements for every record type

Revision ID: 0143
Revises: 0142
Create Date: 2026-11-07

Adds `artefact_placements`: a record of any registered artefact type (other than a requirement or change
request, which keep their own columns) may sit in any number of component/category pairs. Guarded so a database
built from the current models passes.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0143"
down_revision: str | None = "0142"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS artefact_placements (
            id UUID PRIMARY KEY,
            project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            artefact_type VARCHAR(40) NOT NULL,
            artefact_id UUID NOT NULL,
            component_id UUID NOT NULL REFERENCES project_components(id) ON DELETE CASCADE,
            category_id UUID REFERENCES project_categories(id) ON DELETE CASCADE,
            created_by UUID REFERENCES users(id) ON DELETE SET NULL,
            created_at TIMESTAMPTZ NOT NULL
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_artefact_placements_record ON artefact_placements (artefact_type, artefact_id)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_artefact_placements_project_type ON artefact_placements (project_id, artefact_type)"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_artefact_placements_component ON artefact_placements (component_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_artefact_placements_category ON artefact_placements (category_id)")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_artefact_placements_category ON artefact_placements "
        "(artefact_type, artefact_id, component_id, category_id) WHERE category_id IS NOT NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_artefact_placements_component ON artefact_placements "
        "(artefact_type, artefact_id, component_id) WHERE category_id IS NULL"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS artefact_placements")
