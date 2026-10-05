"""Persona data model (Module 2 Phase 1.1)

Revision ID: 0058
Revises: 0057
Create Date: 2026-10-05

Adds the Persona tables (docs/plans/module-02-stakeholders-and-personas-plan.md
Phase 1.1): `persona_type_definitions`/`project_persona_types` (two-tier type
vocabulary), `personas`/`persona_versions` (identity + temporal content, org or
project scope), `project_persona_weights` (per-project weight override), and the
module-local comment/attachment tables.

Existing organisations get the default Primary/Secondary/Negative types
backfilled, since `on_org_created` only seeds organisations created afterwards.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0058"
down_revision: str | None = "0057"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS persona_type_definitions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            name VARCHAR(100) NOT NULL,
            sort_order INTEGER NOT NULL DEFAULT 0,
            is_active BOOLEAN NOT NULL DEFAULT true,
            CONSTRAINT uq_persona_type_definitions_org_name UNIQUE (organization_id, name)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS project_persona_types (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            org_type_id UUID REFERENCES persona_type_definitions(id) ON DELETE SET NULL,
            name_override VARCHAR(100),
            display_order_override INTEGER,
            is_enabled BOOLEAN NOT NULL DEFAULT true,
            CONSTRAINT uq_project_persona_types_project_org_type UNIQUE (project_id, org_type_id),
            CONSTRAINT ck_project_persona_types_local_has_name CHECK (
                org_type_id IS NOT NULL OR name_override IS NOT NULL
            )
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS personas (
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
            CONSTRAINT ck_personas_scope_matches_owner CHECK (
                (scope = 'organization' AND organization_id IS NOT NULL AND project_id IS NULL) OR
                (scope = 'project' AND project_id IS NOT NULL AND organization_id IS NULL)
            )
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_personas_organization_id ON personas (organization_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_personas_project_id ON personas (project_id)")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS persona_versions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            persona_id UUID NOT NULL REFERENCES personas(id) ON DELETE CASCADE,
            version_number INTEGER NOT NULL,
            valid_from TIMESTAMPTZ NOT NULL,
            valid_to TIMESTAMPTZ,
            name VARCHAR(300) NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            org_type_id UUID REFERENCES persona_type_definitions(id),
            project_type_id UUID REFERENCES project_persona_types(id),
            role_title VARCHAR(300) NOT NULL DEFAULT '',
            goals TEXT NOT NULL DEFAULT '',
            needs TEXT NOT NULL DEFAULT '',
            behaviours TEXT NOT NULL DEFAULT '',
            context_environment TEXT NOT NULL DEFAULT '',
            skills_proficiency TEXT NOT NULL DEFAULT '',
            frequency_of_use TEXT NOT NULL DEFAULT '',
            constraints TEXT NOT NULL DEFAULT '',
            weight DOUBLE PRECISION,
            status VARCHAR(20) NOT NULL DEFAULT 'draft',
            owner_id UUID REFERENCES users(id),
            champion_id UUID REFERENCES users(id),
            change_note TEXT NOT NULL DEFAULT '',
            created_by UUID NOT NULL REFERENCES users(id),
            created_at TIMESTAMPTZ NOT NULL,
            UNIQUE (persona_id, version_number),
            CONSTRAINT ck_persona_versions_weight_positive CHECK (weight IS NULL OR weight > 0),
            CONSTRAINT ck_persona_versions_one_type_reference CHECK (
                org_type_id IS NULL OR project_type_id IS NULL
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_persona_versions_current ON persona_versions (persona_id) "
        "WHERE valid_to IS NULL"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS project_persona_weights (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            persona_id UUID NOT NULL REFERENCES personas(id) ON DELETE CASCADE,
            weight DOUBLE PRECISION NOT NULL,
            CONSTRAINT uq_project_persona_weights_project_persona UNIQUE (project_id, persona_id),
            CONSTRAINT ck_project_persona_weights_positive CHECK (weight > 0)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_project_persona_weights_project_id ON project_persona_weights (project_id)")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS persona_comments (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            persona_id UUID NOT NULL REFERENCES personas(id) ON DELETE CASCADE,
            author_id UUID NOT NULL REFERENCES users(id),
            body TEXT NOT NULL,
            edited_at TIMESTAMPTZ
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS persona_comment_files (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            comment_id UUID NOT NULL REFERENCES persona_comments(id) ON DELETE CASCADE,
            file_id UUID NOT NULL REFERENCES file_assets(id) ON DELETE CASCADE,
            uploaded_by UUID NOT NULL REFERENCES users(id)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_persona_comment_files_comment_id ON persona_comment_files (comment_id)")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS persona_files (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            persona_id UUID NOT NULL REFERENCES personas(id) ON DELETE CASCADE,
            file_id UUID NOT NULL REFERENCES file_assets(id) ON DELETE CASCADE,
            linked_by UUID NOT NULL REFERENCES users(id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (persona_id, file_id)
        )
        """
    )
    # Backfill the default types for organisations that already exist.
    op.execute(
        """
        INSERT INTO persona_type_definitions (organization_id, name, sort_order, is_active)
        SELECT o.id, t.name, t.sort_order, true
        FROM organizations o
        CROSS JOIN (VALUES ('Primary', 0), ('Secondary', 1), ('Negative', 2)) AS t(name, sort_order)
        ON CONFLICT (organization_id, name) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS persona_files")
    op.execute("DROP TABLE IF EXISTS persona_comment_files")
    op.execute("DROP TABLE IF EXISTS persona_comments")
    op.execute("DROP TABLE IF EXISTS project_persona_weights")
    op.execute("DROP TABLE IF EXISTS persona_versions")
    op.execute("DROP TABLE IF EXISTS personas")
    op.execute("DROP TABLE IF EXISTS project_persona_types")
    op.execute("DROP TABLE IF EXISTS persona_type_definitions")
