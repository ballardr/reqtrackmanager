"""Requirement completion becomes an overlay marker, not a lifecycle status

Revision ID: 0018
Revises: 0017
Create Date: 2026-08-30

C-G-11 makes a requirement's completion independent of its lifecycle state: an overlay marker that
periodic review may reverse to non-compliant (docs/decisions.md's entry on this migration). A `COMPLETED`
member of `RequirementStatus` conflated the two, so this migration:

1. Adds `requirements.is_completed`/`completed_at`/`completed_by`, mirroring the
   `is_archived`/`archived_at`/`archived_by` overlay already on the table.
2. Backfills them: for each `Requirement` whose current `RequirementVersion.status == 'completed'`,
   sets `is_completed = true` and copies that version's `created_at`/`created_by`.
3. Rewrites every `requirement_versions` row (current and historical) with `status = 'completed'` to
   `'approved'`, because `'completed'` is not a valid `RequirementStatus` value (`app/models/enums.py`).

No enum-type change is needed: `RequirementStatus` is stored through `models.base.str_enum`
(`native_enum=False`), a plain `VARCHAR` with no Postgres type or CHECK constraint.

`IF NOT EXISTS` and an idempotent backfill, as in 0004/0017: a fresh database already has the columns
and no `'completed'` rows.
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

    # A requirement whose current version is 'completed' gets the overlay set, attributed to that
    # version's `created_by`/`created_at`.
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

    # Every `requirement_versions` row (current and historical) with the removed 'completed' status becomes
    # 'approved', the status before completion; completing never changed content.
    op.execute("UPDATE requirement_versions SET status = 'approved' WHERE status = 'completed'")


def downgrade() -> None:
    # The downgrade drops the columns without re-deriving which 'approved' versions were 'completed': a
    # cleared overlay cannot be told apart from a never-completed one, so `is_completed = true` state is lost.
    op.execute("ALTER TABLE requirements DROP COLUMN IF EXISTS completed_by")
    op.execute("ALTER TABLE requirements DROP COLUMN IF EXISTS completed_at")
    op.execute("ALTER TABLE requirements DROP COLUMN IF EXISTS is_completed")
