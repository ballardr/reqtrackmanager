"""External references: `external_references`, and a URL template on external systems.

Revision ID: 0203
Revises: 0202
Create Date: 2026-11-19

One table of pointers from any record to an item in an outside tool, keyed by the registered artefact type string
(no foreign key on the record id; the owning project and organisation cascade), and an optional `url_template` on
the organisation's external systems and a project's rows for them. The systems tables already exist (they were
created for Product Feedback and are now shared), so they only gain the column. Guarded so a database built from the
current models passes.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0203"
down_revision: str | None = "0202"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE external_system_definitions ADD COLUMN IF NOT EXISTS url_template VARCHAR(500)")
    op.execute("ALTER TABLE project_external_systems ADD COLUMN IF NOT EXISTS url_template VARCHAR(500)")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS external_references (
            id UUID PRIMARY KEY,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            artefact_type VARCHAR(64) NOT NULL,
            artefact_id UUID NOT NULL,
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
            org_system_id UUID REFERENCES external_system_definitions(id) ON DELETE CASCADE,
            project_system_id UUID REFERENCES project_external_systems(id) ON DELETE CASCADE,
            key VARCHAR(100) NOT NULL,
            url VARCHAR(500),
            note VARCHAR(500) NOT NULL,
            role VARCHAR(20),
            created_by UUID NOT NULL REFERENCES users(id),
            CONSTRAINT ck_external_references_one_system
                CHECK ((org_system_id IS NOT NULL) <> (project_system_id IS NOT NULL)),
            CONSTRAINT ck_external_references_tier_matches_owner
                CHECK ((project_id IS NULL) = (org_system_id IS NOT NULL))
        )
        """
    )
    for statement in (
        "CREATE INDEX IF NOT EXISTS ix_external_references_record ON external_references (artefact_type, artefact_id)",
        "CREATE INDEX IF NOT EXISTS ix_external_references_organization_id ON external_references (organization_id)",
        "CREATE INDEX IF NOT EXISTS ix_external_references_project_id ON external_references (project_id)",
        "CREATE INDEX IF NOT EXISTS ix_external_references_org_system_id ON external_references (org_system_id)",
        "CREATE INDEX IF NOT EXISTS ix_external_references_project_system_id ON external_references (project_system_id)",
    ):
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS external_references")
    op.execute("ALTER TABLE project_external_systems DROP COLUMN IF EXISTS url_template")
    op.execute("ALTER TABLE external_system_definitions DROP COLUMN IF EXISTS url_template")
