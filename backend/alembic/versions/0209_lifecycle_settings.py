"""Lifecycle configuration: project settings, organisation required states and exemptions.

Revision ID: 0209
Revises: 0208
Create Date: 2026-11-24

Nothing is seeded: with no rows every project uses every state of every record type and no organisation requires
one, so behaviour is unchanged on upgrade. Guarded so a database built from the current models passes.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0209"
down_revision: str | None = "0208"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS project_lifecycle_settings (
            id UUID PRIMARY KEY,
            project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            artefact_type VARCHAR(64) NOT NULL,
            disabled_states JSONB NOT NULL DEFAULT '[]'::jsonb,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            CONSTRAINT uq_project_lifecycle_settings UNIQUE (project_id, artefact_type)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_project_lifecycle_settings_project_id ON project_lifecycle_settings (project_id)")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS organization_lifecycle_requirements (
            id UUID PRIMARY KEY,
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            artefact_type VARCHAR(64) NOT NULL,
            state VARCHAR(64) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            CONSTRAINT uq_org_lifecycle_requirements UNIQUE (organization_id, artefact_type, state)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_organization_lifecycle_requirements_organization_id "
        "ON organization_lifecycle_requirements (organization_id)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS organization_lifecycle_exemptions (
            id UUID PRIMARY KEY,
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            artefact_type VARCHAR(64) NOT NULL,
            project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            include_children BOOLEAN NOT NULL DEFAULT false,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            CONSTRAINT uq_org_lifecycle_exemptions UNIQUE (organization_id, artefact_type, project_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_organization_lifecycle_exemptions_organization_id "
        "ON organization_lifecycle_exemptions (organization_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_organization_lifecycle_exemptions_project_id "
        "ON organization_lifecycle_exemptions (project_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS organization_lifecycle_exemptions")
    op.execute("DROP TABLE IF EXISTS organization_lifecycle_requirements")
    op.execute("DROP TABLE IF EXISTS project_lifecycle_settings")
