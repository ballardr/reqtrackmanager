"""Generic per-project sequence counter (Module 0 — Platform Foundations, Phase 2)

Revision ID: 0042
Revises: 0041
Create Date: 2026-09-21

Per the Phase 0 decision record (docs/decisions.md, "Module 0 (Platform
Foundations) Phase 0"): builds `project_sequence_counters`
(`app.models.sequence.ProjectSequenceCounter`), the shared mechanism every
*new* identified artefact type in the future-modules roadmap (Decision,
Design, Risk, Pain Point, Strategy, Guiding Principle, Open Question,
Stakeholder/Persona) will generate its unique code from, instead of adding
its own `next_<type>_seq` column to `projects` the way
`next_requirement_seq`/`next_action_seq` already do.

`projects.next_requirement_seq`/`next_action_seq` are deliberately left
untouched — this table is additive, for new artefact types only, per the
Phase 0 decision. No rows are backfilled; counter rows are created lazily
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
