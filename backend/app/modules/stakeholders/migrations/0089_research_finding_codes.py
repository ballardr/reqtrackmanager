"""Research findings get project-scoped human codes, FND-001

Revision ID: 0089
Revises: 0088
Create Date: 2026-10-13

Adds `research_findings.unique_code` (unique per project), the same `PREFIX-nnn` shape Risks and
Decisions carry, so a finding can be named and found from the record it is linked to. Existing
findings are numbered per project in the order they were recorded, and the project's
`research_finding` sequence counter is set past the highest number, so a code is never reused.
Guarded throughout: a database built from the current models already has the column.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0089"
down_revision: str | None = "0088"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE research_findings ADD COLUMN IF NOT EXISTS unique_code VARCHAR(64)")
    op.execute(
        """
        UPDATE research_findings f SET unique_code = 'FND-' || lpad(n.seq::text, 3, '0')
        FROM (
            SELECT id, row_number() OVER (PARTITION BY project_id ORDER BY created_at, id) AS seq
            FROM research_findings WHERE unique_code IS NULL
        ) n
        WHERE f.id = n.id
        """
    )
    op.execute(
        """
        INSERT INTO project_sequence_counters (id, created_at, updated_at, project_id, artefact_type, next_seq)
        SELECT gen_random_uuid(), now(), now(), project_id, 'research_finding', count(*) + 1
        FROM research_findings GROUP BY project_id
        ON CONFLICT (project_id, artefact_type) DO NOTHING
        """
    )
    op.execute("ALTER TABLE research_findings ALTER COLUMN unique_code SET NOT NULL")
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_research_findings_project_unique_code') THEN
                ALTER TABLE research_findings
                    ADD CONSTRAINT uq_research_findings_project_unique_code UNIQUE (project_id, unique_code);
            END IF;
        END $$
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE research_findings DROP CONSTRAINT IF EXISTS uq_research_findings_project_unique_code")
    op.execute("ALTER TABLE research_findings DROP COLUMN IF EXISTS unique_code")
    op.execute("DELETE FROM project_sequence_counters WHERE artefact_type = 'research_finding'")
