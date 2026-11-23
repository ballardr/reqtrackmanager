"""Engagements get project-scoped human codes, ENG-001

Revision ID: 0091
Revises: 0090
Create Date: 2026-10-13

Adds `engagements.unique_code` (unique per project), numbering existing
engagements per project in logging order and setting the `engagement` counter
past the highest. Guarded: a database built from the current models has it.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0091"
down_revision: str | None = "0090"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE engagements ADD COLUMN IF NOT EXISTS unique_code VARCHAR(64)")
    op.execute(
        """
        UPDATE engagements e SET unique_code = 'ENG-' || lpad(n.seq::text, 3, '0')
        FROM (
            SELECT id, row_number() OVER (PARTITION BY project_id ORDER BY created_at, id) AS seq
            FROM engagements WHERE unique_code IS NULL
        ) n
        WHERE e.id = n.id
        """
    )
    op.execute(
        """
        INSERT INTO project_sequence_counters (id, created_at, updated_at, project_id, artefact_type, next_seq)
        SELECT gen_random_uuid(), now(), now(), project_id, 'engagement', count(*) + 1
        FROM engagements GROUP BY project_id
        ON CONFLICT (project_id, artefact_type) DO NOTHING
        """
    )
    op.execute("ALTER TABLE engagements ALTER COLUMN unique_code SET NOT NULL")
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_engagements_project_unique_code') THEN
                ALTER TABLE engagements ADD CONSTRAINT uq_engagements_project_unique_code UNIQUE (project_id, unique_code);
            END IF;
        END $$
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE engagements DROP CONSTRAINT IF EXISTS uq_engagements_project_unique_code")
    op.execute("ALTER TABLE engagements DROP COLUMN IF EXISTS unique_code")
    op.execute("DELETE FROM project_sequence_counters WHERE artefact_type = 'engagement'")
