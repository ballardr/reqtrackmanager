"""Requirement completion becomes an overlay marker, not a lifecycle status

Revision ID: 0018
Revises: 0017
Create Date: 2026-08-30

C-G-11 is explicit that a requirement's completion is "independently of
lifecycle state... an overlay marker subject to the potential of periodic
review where it may later be reversed to non-compliant." The previous
implementation baked `COMPLETED` into `RequirementStatus` alongside
`draft`/`reviewed`/`approved`/`archived`, reachable only from `approved` —
contradicting "independently of lifecycle state" (a requirement's own
`status` column and its completion state were really the same column, so
"complete it" and "revert its lifecycle status" were the same irreversible-
without-a-new-version operation). See docs/decisions.md's entry on this
migration for the full reasoning.

This migration:

1. Adds `requirements.is_completed`/`completed_at`/`completed_by`, mirroring
   the existing `is_archived`/`archived_at`/`archived_by` overlay pattern
   already on the same table.
2. Backfills those three columns from whatever is true today: for every
   `Requirement` whose *current* `RequirementVersion.status == 'completed'`,
   sets `is_completed = true` and copies that version's own
   `created_at`/`created_by` (who/when it was actually marked completed,
   since completing a requirement used to write a new version whose
   `created_by`/`created_at` recorded exactly that).
3. Rewrites *every* `requirement_versions` row (current and historical/non-
   current alike) with `status = 'completed'` to `status = 'approved'` —
   `'completed'` is being removed as a valid `RequirementStatus` value
   entirely (`app/models/enums.py`), so no row anywhere in the table may
   keep referencing it, not just the current one per requirement.

No Postgres `ALTER TYPE`/enum-recreation step is needed here, unlike a
typical native-Postgres-enum column drop: `RequirementStatus` is stored via
`models.base.str_enum` (`native_enum=False`), which is a plain `VARCHAR`
with no Postgres `CREATE TYPE`/`CHECK` constraint backing it (see that
helper's own docstring) — removing `COMPLETED` from the Python enum is
purely an application-level validation change; this migration only needs to
touch the actual data.

`IF NOT EXISTS`/idempotent backfill for the same reason 0004/0017 use it:
0001's `create_all()` already creates `requirements` against the *current*
model classes (which already include these three columns) on a brand-new
database, so a plain `ADD COLUMN` would fail there with "already exists";
an already-migrated database from before this revision is genuinely missing
them. The backfill `UPDATE` is a no-op on a fresh database (no `'completed'`
rows exist to find).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE requirements ADD COLUMN IF NOT EXISTS is_completed BOOLEAN NOT NULL DEFAULT false")
    op.execute("ALTER TABLE requirements ADD COLUMN IF NOT EXISTS completed_at TIMESTAMPTZ")
    op.execute(
        "ALTER TABLE requirements ADD COLUMN IF NOT EXISTS completed_by UUID REFERENCES users(id)"
    )

    # Backfill from whatever is true today, before the enum value is
    # dropped from the model: a requirement whose *current* version is
    # 'completed' gets the overlay set, attributed to that version's own
    # created_by/created_at (who/when it was actually marked completed).
    op.execute(
        """
        UPDATE requirements r
        SET is_completed = true,
            completed_at = rv.created_at,
            completed_by = rv.created_by
        FROM requirement_versions rv
        WHERE rv.requirement_id = r.id
          AND rv.valid_to IS NULL
          AND rv.status = 'completed'
        """
    )

    # Every requirement_versions row referencing the removed 'completed'
    # status — current and historical alike — is rewritten to 'approved',
    # the status a requirement was always in immediately before being
    # completed (completing never changed content, so this is a faithful
    # rewrite, not a lossy one).
    op.execute("UPDATE requirement_versions SET status = 'approved' WHERE status = 'completed'")


def downgrade() -> None:
    # The reverse data migration (re-deriving which now-'approved' versions
    # were actually 'completed') is intentionally not attempted — once a
    # completed requirement's overlay has potentially been cleared by a
    # FAILED review outcome or an "Approve and clear completion" change
    # request decision, there is no way to distinguish "was completed, now
    # isn't" from "was never completed" from the data alone. Columns are
    # dropped; any current is_completed=true state is lost on downgrade,
    # same risk profile as any other lossy column removal in this project.
    op.execute("ALTER TABLE requirements DROP COLUMN IF EXISTS completed_by")
    op.execute("ALTER TABLE requirements DROP COLUMN IF EXISTS completed_at")
    op.execute("ALTER TABLE requirements DROP COLUMN IF EXISTS is_completed")
