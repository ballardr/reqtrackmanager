"""Generic per-project sequence counter

Revision ID: 0042
Revises: 0041
Create Date: 2026-09-21

Builds `project_sequence_counters` (`app.models.sequence.ProjectSequenceCounter`; docs/decisions.md,
Platform Foundations), the shared mechanism from which each new identified artefact type generates its
unique code, instead of its own `next_<type>_seq` column on `projects` (as `next_requirement_seq` and
`next_action_seq` are). Those two columns are unchanged. No rows are backfilled; counter rows are created
on first use by `services.sequences.generate_unique_code`.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0042"
down_revision: str | None = "0041"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS project_sequence_counters (
            id UUID PRIMARY KEY,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            artefact_type VARCHAR(20) NOT NULL,
            next_seq INTEGER NOT NULL
        )
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'uq_project_sequence_counters_project_type'
            ) THEN
                ALTER TABLE project_sequence_counters
                    ADD CONSTRAINT uq_project_sequence_counters_project_type
                    UNIQUE (project_id, artefact_type);
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS project_sequence_counters")
