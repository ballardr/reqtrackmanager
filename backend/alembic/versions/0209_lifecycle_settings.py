"""Lifecycle configuration: project settings, organisation required states and exemptions, the skip-steps rule and
approval separation.

Revision ID: 0209
Revises: 0208
Create Date: 2026-11-24

Nothing is seeded: with no rows every project uses every state of every record type and no organisation requires
one and every creator may approve their own record, so behaviour is unchanged on upgrade. Guarded so a database built from the current models passes.
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


    op.execute(
        """
        CREATE TABLE IF NOT EXISTS project_lifecycle_skip_settings (
            id UUID PRIMARY KEY,
            project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            allowed BOOLEAN NOT NULL DEFAULT false,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            CONSTRAINT uq_project_lifecycle_skip_settings UNIQUE (project_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_project_lifecycle_skip_settings_project_id "
        "ON project_lifecycle_skip_settings (project_id)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS organization_lifecycle_skip_policies (
            id UUID PRIMARY KEY,
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            forbidden BOOLEAN NOT NULL DEFAULT false,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            CONSTRAINT uq_org_lifecycle_skip_policies UNIQUE (organization_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_organization_lifecycle_skip_policies_organization_id "
        "ON organization_lifecycle_skip_policies (organization_id)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS organization_lifecycle_skip_exemptions (
            id UUID PRIMARY KEY,
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            include_children BOOLEAN NOT NULL DEFAULT false,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            CONSTRAINT uq_org_lifecycle_skip_exemptions UNIQUE (organization_id, project_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_organization_lifecycle_skip_exemptions_organization_id "
        "ON organization_lifecycle_skip_exemptions (organization_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_organization_lifecycle_skip_exemptions_project_id "
        "ON organization_lifecycle_skip_exemptions (project_id)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS project_approval_separation_settings (
            id UUID PRIMARY KEY,
            project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            artefact_type VARCHAR(64) NOT NULL,
            separate_approver BOOLEAN NOT NULL DEFAULT false,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            CONSTRAINT uq_project_approval_separation_settings UNIQUE (project_id, artefact_type)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_project_approval_separation_settings_project_id "
        "ON project_approval_separation_settings (project_id)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS organization_approval_separation_requirements (
            id UUID PRIMARY KEY,
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            artefact_type VARCHAR(64) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            CONSTRAINT uq_org_approval_separation_requirements UNIQUE (organization_id, artefact_type)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_org_approval_separation_requirements_org_id "
        "ON organization_approval_separation_requirements (organization_id)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS organization_approval_separation_exemptions (
            id UUID PRIMARY KEY,
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            artefact_type VARCHAR(64) NOT NULL,
            project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            include_children BOOLEAN NOT NULL DEFAULT false,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            CONSTRAINT uq_org_approval_separation_exemptions UNIQUE (organization_id, artefact_type, project_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_organization_approval_separation_exemptions_organization_id "
        "ON organization_approval_separation_exemptions (organization_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_organization_approval_separation_exemptions_project_id "
        "ON organization_approval_separation_exemptions (project_id)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS record_self_approvals (
            id UUID PRIMARY KEY,
            artefact_type VARCHAR(64) NOT NULL,
            record_id UUID NOT NULL,
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
            approved_by UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            approved_at TIMESTAMPTZ NOT NULL,
            CONSTRAINT uq_record_self_approvals UNIQUE (artefact_type, record_id)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_record_self_approvals_record_id ON record_self_approvals (record_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_record_self_approvals_organization_id ON record_self_approvals (organization_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_record_self_approvals_project_id ON record_self_approvals (project_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS record_self_approvals")
    op.execute("DROP TABLE IF EXISTS organization_approval_separation_exemptions")
    op.execute("DROP TABLE IF EXISTS organization_approval_separation_requirements")
    op.execute("DROP TABLE IF EXISTS project_approval_separation_settings")
    op.execute("DROP TABLE IF EXISTS organization_lifecycle_skip_exemptions")
    op.execute("DROP TABLE IF EXISTS organization_lifecycle_skip_policies")
    op.execute("DROP TABLE IF EXISTS project_lifecycle_skip_settings")
    op.execute("DROP TABLE IF EXISTS organization_lifecycle_exemptions")
    op.execute("DROP TABLE IF EXISTS organization_lifecycle_requirements")
    op.execute("DROP TABLE IF EXISTS project_lifecycle_settings")
