"""Tags: vocabulary, attachments and the tag mode settings

Revision ID: 0102
Revises: 0101
Create Date: 2026-10-19

Adds `tags` (a project's or an organisation's vocabulary) and `artefact_tags` (a tag on a
record of any registered artefact type), plus `projects.tag_mode` (NULL inherits) and
`organizations.tag_mode` ("free" or "restricted"). Existing requirement keywords are copied
into tags and the `requirement_keywords` table is dropped: a keyword is a tag. Guarded so a
database built from the current models passes.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0102"
down_revision: str | None = "0101"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE projects ADD COLUMN IF NOT EXISTS tag_mode VARCHAR(12)")
    op.execute("ALTER TABLE organizations ADD COLUMN IF NOT EXISTS tag_mode VARCHAR(12) NOT NULL DEFAULT 'free'")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS tags (
            id UUID PRIMARY KEY,
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
            name VARCHAR(40) NOT NULL,
            name_key VARCHAR(40) NOT NULL,
            colour VARCHAR(7),
            created_by UUID REFERENCES users(id) ON DELETE SET NULL,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_tags_organization_id ON tags (organization_id)")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_tags_project_key ON tags (project_id, name_key) WHERE project_id IS NOT NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_tags_org_key ON tags (organization_id, name_key) WHERE project_id IS NULL"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS artefact_tags (
            tag_id UUID NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
            artefact_type VARCHAR(40) NOT NULL,
            artefact_id UUID NOT NULL,
            project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
            created_by UUID REFERENCES users(id) ON DELETE SET NULL,
            created_at TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (tag_id, artefact_type, artefact_id)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_artefact_tags_record ON artefact_tags (artefact_type, artefact_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_artefact_tags_project_type ON artefact_tags (project_id, artefact_type)")

    # Requirement keywords become tags in the requirement's project (keywords were stored lower-cased).
    op.execute(
        """
        DO $$
        BEGIN
            IF to_regclass('requirement_keywords') IS NOT NULL THEN
                CREATE TEMP TABLE _kw ON COMMIT DROP AS
                SELECT r.id AS requirement_id, r.project_id, p.organization_id,
                       left(regexp_replace(btrim(k.keyword), '[[:space:]]+', ' ', 'g'), 40) AS name
                FROM requirement_keywords k
                JOIN requirements r ON r.id = k.requirement_id
                JOIN projects p ON p.id = r.project_id;
                INSERT INTO tags (id, organization_id, project_id, name, name_key, created_at, updated_at)
                SELECT gen_random_uuid(), organization_id, project_id, name, name, now(), now()
                FROM _kw WHERE name <> '' GROUP BY organization_id, project_id, name
                ON CONFLICT DO NOTHING;
                INSERT INTO artefact_tags (tag_id, artefact_type, artefact_id, project_id, created_at)
                SELECT DISTINCT t.id, 'requirement', kw.requirement_id, kw.project_id, now()
                FROM _kw kw JOIN tags t ON t.project_id = kw.project_id AND t.name_key = kw.name
                ON CONFLICT DO NOTHING;
                DROP TABLE requirement_keywords;
            END IF;
        END $$
        """
    )


def downgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS requirement_keywords (
            id UUID PRIMARY KEY,
            requirement_id UUID NOT NULL REFERENCES requirements(id) ON DELETE CASCADE,
            keyword VARCHAR(100) NOT NULL,
            UNIQUE (requirement_id, keyword)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_requirement_keywords_keyword ON requirement_keywords (keyword)")
    op.execute(
        """
        INSERT INTO requirement_keywords (id, requirement_id, keyword)
        SELECT gen_random_uuid(), a.artefact_id, lower(t.name)
        FROM artefact_tags a JOIN tags t ON t.id = a.tag_id
        WHERE a.artefact_type = 'requirement' AND EXISTS (SELECT 1 FROM requirements r WHERE r.id = a.artefact_id)
        ON CONFLICT DO NOTHING
        """
    )
    op.execute("DROP TABLE IF EXISTS artefact_tags")
    op.execute("DROP TABLE IF EXISTS tags")
    op.execute("ALTER TABLE organizations DROP COLUMN IF EXISTS tag_mode")
    op.execute("ALTER TABLE projects DROP COLUMN IF EXISTS tag_mode")
