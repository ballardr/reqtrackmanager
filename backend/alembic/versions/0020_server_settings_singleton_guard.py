"""Enforce ServerSettings singleton semantics at the DB level

Revision ID: 0020
Revises: 0019
Create Date: 2026-08-31

Found incidentally while verifying the follow-up UX batch's Phase D
(docs/decisions.md) — unrelated to that phase's own work, but a real,
previously-undiscovered bug this repo's own "fix issues found, don't defer"
rule requires fixing here rather than filing separately.

`ServerSettings` (`services/branding.py::get_server_settings`) was a
"lazily created singleton row" by convention only: `get_server_settings`
did `settings = db.scalar(select(ServerSettings)); if settings is None:
create one`, with no DB-level constraint preventing two concurrent
requests from both observing "no row yet" and both inserting — a classic
TOCTOU race. This was a *documented*, deliberate omission (the model's own
prior docstring said so explicitly), not an oversight — but live evidence
now shows it happens in practice, not just in theory: a database inspected
during this phase's own Playwright verification sweep had **two** real
`server_settings` rows with different `signup_mode` values, and
`db.scalar(select(ServerSettings))`'s "first row" (no `ORDER BY`) is not
deterministic once more than one exists — different requests can
transiently see different rows, exactly matching several previously-
unexplained flaky `self-signup.spec.ts`/`org-bundle-export-import.spec.ts`
failures this phase's own verification run hit (and, in hindsight,
matching an earlier "genuine, non-reproducing flake" the Phase C entry
above already logged against `test_signup.py` without root-causing it).

Fix, in two parts:
  1. This migration deduplicates any existing extra rows (keeping the most
     recently updated one — the one most likely to reflect the latest real
     admin action, given either row could have "won" any given write
     unpredictably) and adds `singleton_guard` (always `True`, `NOT NULL`,
     `UNIQUE`) so a second row can never be inserted again — a second
     `INSERT` now fails with an `IntegrityError` instead of silently
     succeeding as a duplicate.
  2. `services/branding.py::get_server_settings` (same commit) now catches
     that `IntegrityError` on the racing insert and re-reads instead of
     letting it propagate, so the race becomes "the loser retries and gets
     the winner's row" instead of "the loser also succeeds and creates a
     duplicate."

Guarded by `IF EXISTS`/`ADD COLUMN IF NOT EXISTS`, the same pattern
0014/0017/0018/0019 already use: a brand-new database's `0001_initial.py`
already runs `Base.metadata.create_all()` against the *current* model
classes (which already define `singleton_guard`), so it's created there
from the start with exactly one row — this migration's own dedup/backfill
logic is a no-op on a fresh database, only meaningful for one migrated
from before this revision.
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
