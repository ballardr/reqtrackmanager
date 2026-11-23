"""Enforce ServerSettings singleton semantics at the DB level

Revision ID: 0020
Revises: 0019
Create Date: 2026-08-31

`ServerSettings` (`services/branding.py::get_server_settings`) is a lazily created singleton row. Without
a database constraint, two concurrent requests could both see "no row yet" and both insert (a TOCTOU
race), after which `db.scalar(select(ServerSettings))` (no `ORDER BY`) returns a non-deterministic row
(docs/decisions.md).

Two parts:
  1. This migration deduplicates extra rows, keeping the most recently updated one, and adds
     `singleton_guard` (always `True`, `NOT NULL`, `UNIQUE`), so a second `INSERT` fails with an
     `IntegrityError`.
  2. `get_server_settings` catches that `IntegrityError` on a racing insert and re-reads, so the loser
     receives the winner's row.

Guarded by `IF EXISTS`/`ADD COLUMN IF NOT EXISTS`, as in 0014/0017/0018/0019: a fresh database already
has `singleton_guard` and one row, so the dedup and backfill are no-ops.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        DECLARE
            keep_id uuid;
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.tables WHERE table_name = 'server_settings'
            ) THEN
                -- Keep the most recently updated row (see this migration's
                -- own docstring for why there's no principled way to merge
                -- two independently-diverged rows' field values instead).
                SELECT id INTO keep_id FROM server_settings ORDER BY updated_at DESC, created_at DESC LIMIT 1;
                IF keep_id IS NOT NULL THEN
                    DELETE FROM server_settings WHERE id != keep_id;
                END IF;

                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'server_settings' AND column_name = 'singleton_guard'
                ) THEN
                    ALTER TABLE server_settings ADD COLUMN singleton_guard BOOLEAN NOT NULL DEFAULT true;
                    ALTER TABLE server_settings ADD CONSTRAINT server_settings_singleton_guard_key UNIQUE (singleton_guard);
                END IF;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE server_settings DROP CONSTRAINT IF EXISTS server_settings_singleton_guard_key")
    op.execute("ALTER TABLE server_settings DROP COLUMN IF EXISTS singleton_guard")
