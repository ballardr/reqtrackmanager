"""System Architecture sharing: organisation-owned elements and collections

Revision ID: 0174
Revises: 0173
Create Date: 2026-11-12

An element is owned by a project or by the organisation (`organization_id`, exactly one owner, with its own
code counter), and three tables share elements: `architecture_collections`, their members and their grants (to
a project, optionally with its descendants, or to a group). Guarded with IF NOT EXISTS so a database built from
the current models passes. Downgrading removes organisation-owned elements and the connections that name them.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0174"
down_revision: str | None = "0173"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE architecture_elements ALTER COLUMN project_id DROP NOT NULL")
    op.execute(
        "ALTER TABLE architecture_elements ADD COLUMN IF NOT EXISTS organization_id UUID "
        "REFERENCES organizations(id) ON DELETE CASCADE"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_architecture_elements_organization_id ON architecture_elements (organization_id)"
    )
    op.execute(
        """
        DO $$ BEGIN
            ALTER TABLE architecture_elements ADD CONSTRAINT uq_architecture_elements_org_unique_code
                UNIQUE (organization_id, unique_code);
        EXCEPTION WHEN duplicate_object OR duplicate_table THEN NULL; END $$
        """
    )
    op.execute(
        """
        DO $$ BEGIN
            ALTER TABLE architecture_elements ADD CONSTRAINT ck_architecture_elements_one_owner
                CHECK ((project_id IS NULL) <> (organization_id IS NULL));
        EXCEPTION WHEN duplicate_object THEN NULL; END $$
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS architecture_collections (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
            organization_id UUID REFERENCES organizations(id) ON DELETE CASCADE,
            name VARCHAR(200) NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            creator_id UUID NOT NULL REFERENCES users(id),
            CONSTRAINT uq_architecture_collections_project_name UNIQUE (project_id, name),
            CONSTRAINT uq_architecture_collections_org_name UNIQUE (organization_id, name),
            CONSTRAINT ck_architecture_collections_one_owner CHECK ((project_id IS NULL) <> (organization_id IS NULL))
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_architecture_collections_project_id ON architecture_collections (project_id)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_architecture_collections_organization_id ON architecture_collections (organization_id)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS architecture_collection_members (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            collection_id UUID NOT NULL REFERENCES architecture_collections(id) ON DELETE CASCADE,
            element_id UUID NOT NULL REFERENCES architecture_elements(id) ON DELETE CASCADE,
            CONSTRAINT uq_architecture_collection_members UNIQUE (collection_id, element_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_architecture_collection_members_collection_id "
        "ON architecture_collection_members (collection_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_architecture_collection_members_element_id "
        "ON architecture_collection_members (element_id)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS architecture_collection_grants (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            collection_id UUID NOT NULL REFERENCES architecture_collections(id) ON DELETE CASCADE,
            project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
            group_type VARCHAR(20),
            group_id UUID,
            include_descendants BOOLEAN NOT NULL DEFAULT false,
            created_by UUID NOT NULL REFERENCES users(id),
            CONSTRAINT uq_architecture_collection_grants_project UNIQUE (collection_id, project_id),
            CONSTRAINT uq_architecture_collection_grants_group UNIQUE (collection_id, group_type, group_id),
            CONSTRAINT ck_architecture_collection_grants_one_target CHECK ((project_id IS NULL) <> (group_id IS NULL)),
            CONSTRAINT ck_architecture_collection_grants_descendants CHECK (project_id IS NOT NULL OR NOT include_descendants),
            CONSTRAINT ck_architecture_collection_grants_group_type CHECK (
                group_type IS NULL OR group_type IN ('org_group', 'project_group')
            ),
            CONSTRAINT ck_group_principal CHECK (
                (group_type IS NULL OR group_type IN ('user', 'org_group', 'project_group'))
                AND ((group_type IS NULL) = (group_id IS NULL))
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_architecture_collection_grants_collection_id "
        "ON architecture_collection_grants (collection_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_architecture_collection_grants_project_id ON architecture_collection_grants (project_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS architecture_collection_grants")
    op.execute("DROP TABLE IF EXISTS architecture_collection_members")
    op.execute("DROP TABLE IF EXISTS architecture_collections")
    op.execute(
        """
        DELETE FROM architecture_connections WHERE source_element_id IN (
            SELECT id FROM architecture_elements WHERE project_id IS NULL
        ) OR target_element_id IN (SELECT id FROM architecture_elements WHERE project_id IS NULL)
        """
    )
    op.execute("DELETE FROM architecture_elements WHERE project_id IS NULL")
    op.execute("ALTER TABLE architecture_elements DROP CONSTRAINT IF EXISTS ck_architecture_elements_one_owner")
    op.execute("ALTER TABLE architecture_elements DROP CONSTRAINT IF EXISTS uq_architecture_elements_org_unique_code")
    op.execute("DROP INDEX IF EXISTS ix_architecture_elements_organization_id")
    op.execute("ALTER TABLE architecture_elements DROP COLUMN IF EXISTS organization_id")
    op.execute("ALTER TABLE architecture_elements ALTER COLUMN project_id SET NOT NULL")
