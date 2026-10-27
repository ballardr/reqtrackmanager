"""Report packs and their immutable versions; pack run provenance columns

Revision ID: 0111
Revises: 0110
Create Date: 2026-10-27

Adds `report_packs` (organisation- or project-level, `project_id` NULL for the organisation) and
`report_pack_versions` (one immutable definition per save), and the `pack_run_id` / `report_key` columns of
`generated_reports`. Guarded: a database built from the current models already has them.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0111"
down_revision: str | None = "0110"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS report_packs (
            id UUID PRIMARY KEY,
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
            name VARCHAR(200) NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            current_version INTEGER NOT NULL DEFAULT 1,
            created_by UUID REFERENCES users(id) ON DELETE SET NULL,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL,
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_report_packs_organization_id ON report_packs (organization_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_report_packs_project_id ON report_packs (project_id)")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_report_packs_org_name ON report_packs (organization_id, name) "
        "WHERE project_id IS NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_report_packs_project_name ON report_packs (project_id, name) "
        "WHERE project_id IS NOT NULL"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS report_pack_versions (
            id UUID PRIMARY KEY,
            pack_id UUID NOT NULL REFERENCES report_packs(id) ON DELETE CASCADE,
            version INTEGER NOT NULL,
            schema_version INTEGER NOT NULL,
            definition JSONB NOT NULL,
            definition_hash VARCHAR(64) NOT NULL,
            comment VARCHAR(500) NOT NULL DEFAULT '',
            created_by UUID REFERENCES users(id) ON DELETE SET NULL,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL,
            CONSTRAINT uq_report_pack_versions_pack_version UNIQUE (pack_id, version)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_report_pack_versions_pack_id ON report_pack_versions (pack_id)")
    op.execute("ALTER TABLE generated_reports ADD COLUMN IF NOT EXISTS pack_run_id UUID")
    op.execute("ALTER TABLE generated_reports ADD COLUMN IF NOT EXISTS report_key VARCHAR(200)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_generated_reports_pack_run_id ON generated_reports (pack_run_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_generated_reports_pack_run_id")
    op.execute("ALTER TABLE generated_reports DROP COLUMN IF EXISTS report_key")
    op.execute("ALTER TABLE generated_reports DROP COLUMN IF EXISTS pack_run_id")
    op.execute("DROP TABLE IF EXISTS report_pack_versions")
    op.execute("DROP TABLE IF EXISTS report_packs")
