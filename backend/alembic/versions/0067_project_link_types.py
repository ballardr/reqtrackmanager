"""Project-level link types, per-project visibility, project rules, org lock

Revision ID: 0067
Revises: 0066
Create Date: 2026-10-06

Adds `requirement_link_type_definitions.project_id` (NULL = organisation-wide,
the existing meaning), swaps the per-organisation name uniqueness for two
partial unique indexes (org-wide per organisation, local per project),
adds `project_link_type_visibility` (a project hides/re-shows a link type; the
nearest row up the project chain wins), adds `artefact_type_link_rules.project_id`
with the same partial-index treatment, and adds
`organizations.project_customisation_locks` (JSONB list of vocabularies projects
may not customise; empty by default, so projects may customise).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0067"
down_revision: str | None = "0066"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Adds the project scope columns, the visibility table and the org lock column."""
    op.execute(
        "ALTER TABLE requirement_link_type_definitions "
        "ADD COLUMN IF NOT EXISTS project_id UUID REFERENCES projects(id) ON DELETE CASCADE"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_requirement_link_type_definitions_project_id "
        "ON requirement_link_type_definitions (project_id)"
    )
    op.execute(
        "ALTER TABLE requirement_link_type_definitions "
        "DROP CONSTRAINT IF EXISTS uq_requirement_link_type_definitions_org_forward"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_requirement_link_type_definitions_org_forward "
        "ON requirement_link_type_definitions (organization_id, forward_name) WHERE project_id IS NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_requirement_link_type_definitions_project_forward "
        "ON requirement_link_type_definitions (project_id, forward_name) WHERE project_id IS NOT NULL"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS project_link_type_visibility (
            project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            link_type_id UUID NOT NULL REFERENCES requirement_link_type_definitions(id) ON DELETE CASCADE,
            hidden BOOLEAN NOT NULL DEFAULT true,
            PRIMARY KEY (project_id, link_type_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_project_link_type_visibility_link_type "
        "ON project_link_type_visibility (link_type_id)"
    )

    op.execute(
        "ALTER TABLE artefact_type_link_rules "
        "ADD COLUMN IF NOT EXISTS project_id UUID REFERENCES projects(id) ON DELETE CASCADE"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_artefact_type_link_rules_project_id ON artefact_type_link_rules (project_id)")
    op.execute("ALTER TABLE artefact_type_link_rules DROP CONSTRAINT IF EXISTS uq_artefact_type_link_rules_org_type")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_artefact_type_link_rules_org_type "
        "ON artefact_type_link_rules (organization_id, artefact_type) WHERE project_id IS NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_artefact_type_link_rules_project_type "
        "ON artefact_type_link_rules (project_id, artefact_type) WHERE project_id IS NOT NULL"
    )

    op.execute(
        "ALTER TABLE organizations ADD COLUMN IF NOT EXISTS project_customisation_locks JSONB NOT NULL DEFAULT '[]'::jsonb"
    )


def downgrade() -> None:
    """Removes project-scoped rows and the added structures, restoring the org-wide uniqueness."""
    op.execute("ALTER TABLE organizations DROP COLUMN IF EXISTS project_customisation_locks")

    op.execute("DELETE FROM artefact_type_link_rules WHERE project_id IS NOT NULL")
    op.execute("DROP INDEX IF EXISTS uq_artefact_type_link_rules_project_type")
    op.execute("DROP INDEX IF EXISTS uq_artefact_type_link_rules_org_type")
    op.execute("DROP INDEX IF EXISTS ix_artefact_type_link_rules_project_id")
    op.execute("ALTER TABLE artefact_type_link_rules DROP COLUMN IF EXISTS project_id")
    op.execute(
        "ALTER TABLE artefact_type_link_rules ADD CONSTRAINT uq_artefact_type_link_rules_org_type "
        "UNIQUE (organization_id, artefact_type)"
    )

    op.execute("DROP TABLE IF EXISTS project_link_type_visibility")

    # Links of a project-local type must go before the type can: the link rows have no cascade.
    op.execute(
        "DELETE FROM artefact_links WHERE link_type_id IN "
        "(SELECT id FROM requirement_link_type_definitions WHERE project_id IS NOT NULL)"
    )
    op.execute("DELETE FROM requirement_link_type_definitions WHERE project_id IS NOT NULL")
    op.execute("DROP INDEX IF EXISTS uq_requirement_link_type_definitions_project_forward")
    op.execute("DROP INDEX IF EXISTS uq_requirement_link_type_definitions_org_forward")
    op.execute("DROP INDEX IF EXISTS ix_requirement_link_type_definitions_project_id")
    op.execute("ALTER TABLE requirement_link_type_definitions DROP COLUMN IF EXISTS project_id")
    op.execute(
        "ALTER TABLE requirement_link_type_definitions ADD CONSTRAINT uq_requirement_link_type_definitions_org_forward "
        "UNIQUE (organization_id, forward_name)"
    )
