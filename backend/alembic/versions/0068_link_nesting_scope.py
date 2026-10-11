"""Link-type nesting scope and cross-level link project columns

Revision ID: 0068
Revises: 0067
Create Date: 2026-10-11

Adds `requirement_link_type_definitions.nesting_scope` (whether a link type may
join a project and its ancestor/descendant, and which end may sit higher;
existing and new types default to `ancestor_either_way`) and
`artefact_links.source_project_id`/`target_project_id` (set only for a link
between a project and its ancestor or descendant; NULL for every existing
same-project link, so nothing existing changes meaning).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0068"
down_revision: str | None = "0067"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Adds the nesting-scope column and the cross-level link project columns."""
    op.execute(
        "ALTER TABLE requirement_link_type_definitions "
        "ADD COLUMN IF NOT EXISTS nesting_scope VARCHAR(30) NOT NULL DEFAULT 'ancestor_either_way'"
    )
    op.execute(
        "ALTER TABLE artefact_links "
        "ADD COLUMN IF NOT EXISTS source_project_id UUID REFERENCES projects(id) ON DELETE CASCADE, "
        "ADD COLUMN IF NOT EXISTS target_project_id UUID REFERENCES projects(id) ON DELETE CASCADE"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_artefact_links_source_project ON artefact_links (source_project_id) "
        "WHERE source_project_id IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_artefact_links_target_project ON artefact_links (target_project_id) "
        "WHERE target_project_id IS NOT NULL"
    )


def downgrade() -> None:
    """Removes cross-level links (they cannot exist without the columns) and the added columns."""
    op.execute("DELETE FROM artefact_links WHERE source_project_id IS NOT NULL")
    op.execute("DROP INDEX IF EXISTS ix_artefact_links_target_project")
    op.execute("DROP INDEX IF EXISTS ix_artefact_links_source_project")
    op.execute("ALTER TABLE artefact_links DROP COLUMN IF EXISTS target_project_id, DROP COLUMN IF EXISTS source_project_id")
    op.execute("ALTER TABLE requirement_link_type_definitions DROP COLUMN IF EXISTS nesting_scope")
