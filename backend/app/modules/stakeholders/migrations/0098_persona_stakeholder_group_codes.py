"""Personas, stakeholders and stakeholder groups get human codes, PER-001, STK-001 and SGP-001

Revision ID: 0098
Revises: 0097
Create Date: 2026-10-18

Adds `unique_code` numbered per project or organisation (existing rows in
creation order, counter past the highest). Guarded and repeatable.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0098"
down_revision: str | None = "0097"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TARGETS = (("personas", "persona", "PER"), ("stakeholders", "stakeholder", "STK"), ("stakeholder_groups", "stakeholder_group", "SGP"))


def _constraint(table: str, owner: str) -> str:
    return f"uq_{table}_{owner}_unique_code"


def upgrade() -> None:
    for table, artefact_type, prefix in _TARGETS:
        op.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS unique_code VARCHAR(64)")
        for owner, counters in (("project", "project_sequence_counters"), ("organization", "organization_sequence_counters")):
            column = f"{owner}_id"
            op.execute(
                f"""
                UPDATE {table} t SET unique_code = '{prefix}-' || lpad(n.seq::text, 3, '0')
                FROM (
                    SELECT id, row_number() OVER (PARTITION BY {column} ORDER BY created_at, id) AS seq
                    FROM {table} WHERE unique_code IS NULL AND {column} IS NOT NULL
                ) n
                WHERE t.id = n.id
                """
            )
            op.execute(
                f"""
                INSERT INTO {counters} (id, created_at, updated_at, {column}, artefact_type, next_seq)
                SELECT gen_random_uuid(), now(), now(), {column}, '{artefact_type}', count(*) + 1
                FROM {table} WHERE {column} IS NOT NULL GROUP BY {column}
                ON CONFLICT ({column}, artefact_type)
                DO UPDATE SET next_seq = GREATEST({counters}.next_seq, EXCLUDED.next_seq)
                """
            )
        op.execute(f"ALTER TABLE {table} ALTER COLUMN unique_code SET NOT NULL")
        for owner in ("project", "organization"):
            constraint = _constraint(table, owner)
            op.execute(
                f"""
                DO $$
                BEGIN
                    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = '{constraint}') THEN
                        ALTER TABLE {table} ADD CONSTRAINT {constraint} UNIQUE ({owner}_id, unique_code);
                    END IF;
                END $$
                """
            )


def downgrade() -> None:
    for table, artefact_type, _prefix in _TARGETS:
        for owner, counters in (("project", "project_sequence_counters"), ("organization", "organization_sequence_counters")):
            op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {_constraint(table, owner)}")
            op.execute(f"DELETE FROM {counters} WHERE artefact_type = '{artefact_type}'")
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS unique_code")
