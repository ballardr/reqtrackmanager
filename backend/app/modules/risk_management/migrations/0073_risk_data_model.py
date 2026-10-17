"""Risk Management data model

Revision ID: 0073
Revises: 0072
Create Date: 2026-10-12

Adds the Risk tables:
`risk_type_definitions`/`project_risk_types` (two-tier type vocabulary),
`risks`/`risk_versions` (identity + temporal content, project scope) and the
module-local comment/attachment tables.

Existing organisations get the default Risk types backfilled, since
`on_org_created` only seeds organisations created afterwards. The `risk`
scoring levels are seeded by core's `sync_scoring_levels` at process start.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0073"
down_revision: str | None = "0072"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DEFAULT_TYPES = (
    "Safety", "Technical", "Reliability", "Performance", "Security", "Compliance", "Operational", "Schedule",
    "Cost", "Supply chain", "Integration", "Environmental",
)


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS risk_type_definitions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            name VARCHAR(100) NOT NULL,
            sort_order INTEGER NOT NULL DEFAULT 0,
            is_active BOOLEAN NOT NULL DEFAULT true,
            CONSTRAINT uq_risk_type_definitions_org_name UNIQUE (organization_id, name)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS project_risk_types (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            org_type_id UUID REFERENCES risk_type_definitions(id) ON DELETE SET NULL,
            name_override VARCHAR(100),
            display_order_override INTEGER,
            is_enabled BOOLEAN NOT NULL DEFAULT true,
            CONSTRAINT uq_project_risk_types_project_org_type UNIQUE (project_id, org_type_id),
            CONSTRAINT ck_project_risk_types_local_has_name CHECK (org_type_id IS NOT NULL OR name_override IS NOT NULL)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS risks (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            unique_code VARCHAR(64) NOT NULL,
            creator_id UUID NOT NULL REFERENCES users(id),
            is_archived BOOLEAN NOT NULL DEFAULT false,
            archived_at TIMESTAMPTZ,
            archived_by UUID REFERENCES users(id),
            CONSTRAINT uq_risks_project_unique_code UNIQUE (project_id, unique_code)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_risks_project_id ON risks (project_id)")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS risk_versions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            risk_id UUID NOT NULL REFERENCES risks(id) ON DELETE CASCADE,
            version_number INTEGER NOT NULL,
            valid_from TIMESTAMPTZ NOT NULL,
            valid_to TIMESTAMPTZ,
            title VARCHAR(300) NOT NULL,
            statement TEXT NOT NULL DEFAULT '',
            cause TEXT NOT NULL DEFAULT '',
            risk_event TEXT NOT NULL DEFAULT '',
            consequence TEXT NOT NULL DEFAULT '',
            project_type_id UUID REFERENCES project_risk_types(id) ON DELETE SET NULL,
            treatment_strategy VARCHAR(20),
            acceptance_criteria TEXT NOT NULL DEFAULT '',
            inherent_likelihood_level_id UUID REFERENCES scoring_levels(id) ON DELETE SET NULL,
            inherent_consequence_level_id UUID REFERENCES scoring_levels(id) ON DELETE SET NULL,
            inherent_detectability_level_id UUID REFERENCES scoring_levels(id) ON DELETE SET NULL,
            residual_likelihood_level_id UUID REFERENCES scoring_levels(id) ON DELETE SET NULL,
            residual_consequence_level_id UUID REFERENCES scoring_levels(id) ON DELETE SET NULL,
            residual_detectability_level_id UUID REFERENCES scoring_levels(id) ON DELETE SET NULL,
            status VARCHAR(30) NOT NULL DEFAULT 'identified',
            owner_id UUID REFERENCES users(id),
            review_date DATE,
            change_note TEXT NOT NULL DEFAULT '',
            created_by UUID NOT NULL REFERENCES users(id),
            created_at TIMESTAMPTZ NOT NULL,
            UNIQUE (risk_id, version_number)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_risk_versions_current ON risk_versions (risk_id) WHERE valid_to IS NULL")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS risk_comments (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            risk_id UUID NOT NULL REFERENCES risks(id) ON DELETE CASCADE,
            author_id UUID NOT NULL REFERENCES users(id),
            body TEXT NOT NULL,
            edited_at TIMESTAMPTZ
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS risk_comment_files (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            comment_id UUID NOT NULL REFERENCES risk_comments(id) ON DELETE CASCADE,
            file_id UUID NOT NULL REFERENCES file_assets(id) ON DELETE CASCADE,
            uploaded_by UUID NOT NULL REFERENCES users(id)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_risk_comment_files_comment_id ON risk_comment_files (comment_id)")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS risk_files (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            risk_id UUID NOT NULL REFERENCES risks(id) ON DELETE CASCADE,
            file_id UUID NOT NULL REFERENCES file_assets(id) ON DELETE CASCADE,
            linked_by UUID NOT NULL REFERENCES users(id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (risk_id, file_id)
        )
        """
    )
    # Backfill the default types for organisations that already exist.
    values = ", ".join(f"('{name}', {i})" for i, name in enumerate(_DEFAULT_TYPES))
    op.execute(
        f"""
        INSERT INTO risk_type_definitions (organization_id, name, sort_order, is_active)
        SELECT o.id, t.name, t.sort_order, true
        FROM organizations o
        CROSS JOIN (VALUES {values}) AS t(name, sort_order)
        ON CONFLICT (organization_id, name) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS risk_files")
    op.execute("DROP TABLE IF EXISTS risk_comment_files")
    op.execute("DROP TABLE IF EXISTS risk_comments")
    op.execute("DROP TABLE IF EXISTS risk_versions")
    op.execute("DROP TABLE IF EXISTS risks")
    op.execute("DROP TABLE IF EXISTS project_risk_types")
    op.execute("DROP TABLE IF EXISTS risk_type_definitions")
