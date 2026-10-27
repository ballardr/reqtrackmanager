"""Saved variable sets for report packs, and per-project overrides of them

Revision ID: 0112
Revises: 0111
Create Date: 2026-10-27

Adds `report_pack_variable_sets` (named values for a pack's variables, defined with the pack or added by a project)
and `report_pack_set_overrides` (one project's values layered over a pack-defined set). Guarded: a database built
from the current models already has both.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0112"
down_revision: str | None = "0111"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS report_pack_variable_sets (
            id UUID PRIMARY KEY,
            pack_id UUID NOT NULL REFERENCES report_packs(id) ON DELETE CASCADE,
            project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
            name VARCHAR(200) NOT NULL,
            variable_values JSONB NOT NULL,
            created_by UUID REFERENCES users(id) ON DELETE SET NULL,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL,
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_report_pack_variable_sets_pack_id ON report_pack_variable_sets (pack_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_report_pack_variable_sets_project_id ON report_pack_variable_sets (project_id)")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_report_pack_sets_pack_name ON report_pack_variable_sets (pack_id, name) "
        "WHERE project_id IS NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_report_pack_sets_project_name ON report_pack_variable_sets "
        "(pack_id, project_id, name) WHERE project_id IS NOT NULL"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS report_pack_set_overrides (
            id UUID PRIMARY KEY,
            set_id UUID NOT NULL REFERENCES report_pack_variable_sets(id) ON DELETE CASCADE,
            project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            variable_values JSONB NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL,
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
            CONSTRAINT uq_report_pack_set_overrides_set_project UNIQUE (set_id, project_id)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_report_pack_set_overrides_set_id ON report_pack_set_overrides (set_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_report_pack_set_overrides_project_id ON report_pack_set_overrides (project_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS report_pack_set_overrides")
    op.execute("DROP TABLE IF EXISTS report_pack_variable_sets")
