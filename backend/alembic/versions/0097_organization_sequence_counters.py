"""Organisation-level sequence counters for organisation-scoped record codes

Revision ID: 0097
Revises: 0096
Create Date: 2026-10-18

Adds `organization_sequence_counters`, the organisation twin of `project_sequence_counters`:
one never-reused counter per `(organization, artefact_type)`, behind the codes of records an
organisation owns (`PER-001`, shown qualified as `ACME-PER-001`). Guarded: a database built from
the current models already has the table.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0097"
down_revision: str | None = "0096"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS organization_sequence_counters (
            id UUID PRIMARY KEY,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            artefact_type VARCHAR(40) NOT NULL,
            next_seq INTEGER NOT NULL,
            CONSTRAINT uq_organization_sequence_counters_org_type UNIQUE (organization_id, artefact_type)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS organization_sequence_counters")
