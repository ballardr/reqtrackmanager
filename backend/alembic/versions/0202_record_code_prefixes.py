"""Record code prefix overrides: `organization_code_prefixes` and `project_code_prefixes`.

Revision ID: 0202
Revises: 0201
Create Date: 2026-11-19

A sparse override of the prefix new records of one artefact type are numbered with (`ADR-006` for `DEC-006`), per
organisation and per project. No row means "follow the next tier", so nothing is backfilled: every existing
record keeps its stored code and every counter is untouched. Guarded so a database built from the current models
passes.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0202"
down_revision: str | None = "0201"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS organization_code_prefixes (
            id UUID PRIMARY KEY,
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            artefact_type VARCHAR(40) NOT NULL,
            prefix VARCHAR(5) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            CONSTRAINT uq_organization_code_prefixes_org_type UNIQUE (organization_id, artefact_type)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_organization_code_prefixes_organization_id "
        "ON organization_code_prefixes (organization_id)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS project_code_prefixes (
            id UUID PRIMARY KEY,
            project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            artefact_type VARCHAR(40) NOT NULL,
            prefix VARCHAR(5) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            CONSTRAINT uq_project_code_prefixes_project_type UNIQUE (project_id, artefact_type)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_project_code_prefixes_project_id ON project_code_prefixes (project_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS project_code_prefixes")
    op.execute("DROP TABLE IF EXISTS organization_code_prefixes")
