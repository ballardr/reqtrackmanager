"""Stakeholder data model (Module 2 Phase 1.2)

Revision ID: 0059
Revises: 0058
Create Date: 2026-10-05

Adds the Stakeholder tables (docs/plans/module-02-stakeholders-and-personas-plan.md
Phase 1.2): `stakeholder_type_definitions`/`project_stakeholder_types`
(two-tier type vocabulary), `stakeholders`/`stakeholder_versions` (identity +
temporal content, org or project scope, with the Influence/Interest scoring
level references, engagement cadence and optional platform-user link) and the
module-local comment/attachment tables.

The versions' type references are `ON DELETE SET NULL` (see 0060 for why).

Existing organisations get the default §10.2 types backfilled, since
`on_org_created` only seeds organisations created afterwards. Scoring levels
for the new `stakeholder` scheme are seeded by `sync_scoring_levels` at
process start, so need no backfill here.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0059"
down_revision: str | None = "0058"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DEFAULT_TYPES = (
    "Customer", "End user", "Operator", "Maintainer", "Service engineer", "Business owner", "Project sponsor",
    "Regulator", "Supplier", "Internal engineering team", "Support organisation",
)


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS stakeholder_type_definitions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            name VARCHAR(100) NOT NULL,
            sort_order INTEGER NOT NULL DEFAULT 0,
            is_active BOOLEAN NOT NULL DEFAULT true,
            CONSTRAINT uq_stakeholder_type_definitions_org_name UNIQUE (organization_id, name)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS project_stakeholder_types (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            org_type_id UUID REFERENCES stakeholder_type_definitions(id) ON DELETE SET NULL,
            name_override VARCHAR(100),
            display_order_override INTEGER,
            is_enabled BOOLEAN NOT NULL DEFAULT true,
            CONSTRAINT uq_project_stakeholder_types_project_org_type UNIQUE (project_id, org_type_id),
            CONSTRAINT ck_project_stakeholder_types_local_has_name CHECK (
                org_type_id IS NOT NULL OR name_override IS NOT NULL
            )
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS stakeholders (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            scope VARCHAR(20) NOT NULL,
            organization_id UUID REFERENCES organizations(id) ON DELETE CASCADE,
            project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
            creator_id UUID NOT NULL REFERENCES users(id),
            is_archived BOOLEAN NOT NULL DEFAULT false,
            archived_at TIMESTAMPTZ,
            archived_by UUID REFERENCES users(id),
            CONSTRAINT ck_stakeholders_scope_matches_owner CHECK (
                (scope = 'organization' AND organization_id IS NOT NULL AND project_id IS NULL) OR
                (scope = 'project' AND project_id IS NOT NULL AND organization_id IS NULL)
            )
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_stakeholders_organization_id ON stakeholders (organization_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_stakeholders_project_id ON stakeholders (project_id)")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS stakeholder_versions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            stakeholder_id UUID NOT NULL REFERENCES stakeholders(id) ON DELETE CASCADE,
            version_number INTEGER NOT NULL,
            valid_from TIMESTAMPTZ NOT NULL,
            valid_to TIMESTAMPTZ,
            name VARCHAR(300) NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            org_type_id UUID REFERENCES stakeholder_type_definitions(id) ON DELETE SET NULL,
            project_type_id UUID REFERENCES project_stakeholder_types(id) ON DELETE SET NULL,
            role VARCHAR(300) NOT NULL DEFAULT '',
            organisation_group VARCHAR(300) NOT NULL DEFAULT '',
            interests TEXT NOT NULL DEFAULT '',
            responsibilities TEXT NOT NULL DEFAULT '',
            goals_needs TEXT NOT NULL DEFAULT '',
            priorities TEXT NOT NULL DEFAULT '',
            constraints TEXT NOT NULL DEFAULT '',
            workflows_scenarios TEXT NOT NULL DEFAULT '',
            contact_info TEXT NOT NULL DEFAULT '',
            target_cadence VARCHAR(20),
            availability_constraints TEXT NOT NULL DEFAULT '',
            influence_level_id UUID REFERENCES scoring_levels(id) ON DELETE SET NULL,
            interest_level_id UUID REFERENCES scoring_levels(id) ON DELETE SET NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'draft',
            owner_id UUID REFERENCES users(id),
            user_id UUID REFERENCES users(id),
            change_note TEXT NOT NULL DEFAULT '',
            created_by UUID NOT NULL REFERENCES users(id),
            created_at TIMESTAMPTZ NOT NULL,
            UNIQUE (stakeholder_id, version_number),
            CONSTRAINT ck_stakeholder_versions_one_type_reference CHECK (
                org_type_id IS NULL OR project_type_id IS NULL
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_stakeholder_versions_current ON stakeholder_versions (stakeholder_id) "
        "WHERE valid_to IS NULL"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS stakeholder_comments (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            stakeholder_id UUID NOT NULL REFERENCES stakeholders(id) ON DELETE CASCADE,
            author_id UUID NOT NULL REFERENCES users(id),
            body TEXT NOT NULL,
            edited_at TIMESTAMPTZ
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS stakeholder_comment_files (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            comment_id UUID NOT NULL REFERENCES stakeholder_comments(id) ON DELETE CASCADE,
            file_id UUID NOT NULL REFERENCES file_assets(id) ON DELETE CASCADE,
            uploaded_by UUID NOT NULL REFERENCES users(id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_stakeholder_comment_files_comment_id ON stakeholder_comment_files (comment_id)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS stakeholder_files (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            stakeholder_id UUID NOT NULL REFERENCES stakeholders(id) ON DELETE CASCADE,
            file_id UUID NOT NULL REFERENCES file_assets(id) ON DELETE CASCADE,
            linked_by UUID NOT NULL REFERENCES users(id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (stakeholder_id, file_id)
        )
        """
    )
    values = ", ".join(f"('{name}', {i})" for i, name in enumerate(_DEFAULT_TYPES))
    op.execute(
        f"""
        INSERT INTO stakeholder_type_definitions (organization_id, name, sort_order, is_active)
        SELECT o.id, t.name, t.sort_order, true
        FROM organizations o
        CROSS JOIN (VALUES {values}) AS t(name, sort_order)
        ON CONFLICT (organization_id, name) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS stakeholder_files")
    op.execute("DROP TABLE IF EXISTS stakeholder_comment_files")
    op.execute("DROP TABLE IF EXISTS stakeholder_comments")
    op.execute("DROP TABLE IF EXISTS stakeholder_versions")
    op.execute("DROP TABLE IF EXISTS stakeholders")
    op.execute("DROP TABLE IF EXISTS project_stakeholder_types")
    op.execute("DROP TABLE IF EXISTS stakeholder_type_definitions")
