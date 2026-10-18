"""Pain points and open questions get project-scoped human codes, PP-001 and OQ-001

Revision ID: 0093
Revises: 0092
Create Date: 2026-10-18

Adds `unique_code` (unique per project) to `pain_points` and `open_questions`, the `PREFIX-nnn` shape
every other record type carries.
Existing rows are numbered per project in the order they were created and the project's sequence
counter is set past the highest number, so a code is never reused. Guarded throughout: a database
built from the current models already has the columns.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0093"
down_revision: str | None = "0092"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TARGETS = (
    ("pain_points", "pain_point", "PP"),
    ("open_questions", "open_question", "OQ"),
)


def upgrade() -> None:
    for table, artefact_type, prefix in _TARGETS:
        constraint = f"uq_{table}_project_unique_code"
        op.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS unique_code VARCHAR(64)")
        op.execute(
            f"""
            UPDATE {table} t SET unique_code = '{prefix}-' || lpad(n.seq::text, 3, '0')
            FROM (
                SELECT id, row_number() OVER (PARTITION BY project_id ORDER BY created_at, id) AS seq
                FROM {table} WHERE unique_code IS NULL
            ) n
            WHERE t.id = n.id
            """
        )
        op.execute(
            f"""
            INSERT INTO project_sequence_counters (id, created_at, updated_at, project_id, artefact_type, next_seq)
            SELECT gen_random_uuid(), now(), now(), project_id, '{artefact_type}', count(*) + 1
            FROM {table} GROUP BY project_id
            ON CONFLICT (project_id, artefact_type) DO NOTHING
            """
        )
        op.execute(f"ALTER TABLE {table} ALTER COLUMN unique_code SET NOT NULL")
        op.execute(
            f"""
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = '{constraint}') THEN
                    ALTER TABLE {table} ADD CONSTRAINT {constraint} UNIQUE (project_id, unique_code);
                END IF;
            END $$
            """
        )


def downgrade() -> None:
    for table, artefact_type, _prefix in _TARGETS:
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS uq_{table}_project_unique_code")
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS unique_code")
        op.execute(f"DELETE FROM project_sequence_counters WHERE artefact_type = '{artefact_type}'")
