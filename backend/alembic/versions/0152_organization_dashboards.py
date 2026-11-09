"""Organisation dashboards

Revision ID: 0152
Revises: 0151
Create Date: 2026-11-09

Adds `organization_dashboards` (the pages of widgets on an organisation's overview) and
`organization_dashboard_viewers` (the users and groups a restricted page is limited to). Seeds nothing: an
organisation with no row shows the built-in Overview page. Guarded so a database built from the current models
passes.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0152"
down_revision: str | None = "0151"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS organization_dashboards (
            id UUID PRIMARY KEY,
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            name VARCHAR(100) NOT NULL,
            position INTEGER NOT NULL DEFAULT 0,
            is_default BOOLEAN NOT NULL DEFAULT FALSE,
            layout JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            CONSTRAINT uq_organization_dashboards_name UNIQUE (organization_id, name)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_organization_dashboards_organization_id ON organization_dashboards (organization_id)")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS organization_dashboard_viewers (
            id UUID PRIMARY KEY,
            dashboard_id UUID NOT NULL REFERENCES organization_dashboards(id) ON DELETE CASCADE,
            viewer_type VARCHAR(20) NOT NULL,
            viewer_id UUID NOT NULL,
            CONSTRAINT uq_organization_dashboard_viewers UNIQUE (dashboard_id, viewer_type, viewer_id),
            CONSTRAINT ck_viewer_principal CHECK (viewer_type IN ('user', 'org_group', 'project_group'))
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_organization_dashboard_viewers_dashboard_id ON organization_dashboard_viewers (dashboard_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS organization_dashboard_viewers")
    op.execute("DROP TABLE IF EXISTS organization_dashboards")
