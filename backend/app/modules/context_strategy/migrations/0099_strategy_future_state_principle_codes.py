"""Strategies, future states and guiding principles get human codes, STR-001, FUT-001 and GP-001

Revision ID: 0099
Revises: 0098
Create Date: 2026-10-18

Adds `unique_code` to `strategies`, `future_states` and `guiding_principles`, which exist at two scopes. A project-scoped row is numbered within
its project (counter in `project_sequence_counters`), an organisation-scoped row within its
organisation (`organization_sequence_counters`, created by 0097); each is unique per owner.
Existing rows are numbered in the order they were created and the counter is set past the highest
number, so a code is never reused. Guarded throughout: a database built from the current models
already has the columns.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0099"
down_revision: str | None = "0098"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TARGETS = (("strategies", "strategy", "STR"), ("future_states", "future_state", "FUT"), ("guiding_principles", "guiding_principle", "GP"))


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
