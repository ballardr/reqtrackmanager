"""Decision owner and decision maker become principals

Revision ID: 0076
Revises: 0075
Create Date: 2026-10-12

`decisions.owner_id` and `decisions.decision_maker_id` may now name a user, an
organisation group or a project group.
Each gets a `<name>_type` column (existing rows backfill to `user`), the foreign
key to `users` is dropped (the id now points at one of three tables; the
service validates it), and a check constraint keeps the pair consistent.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0076"
down_revision: str | None = "0075"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TYPES = "'user', 'org_group', 'project_group'"


def upgrade() -> None:
    op.execute("ALTER TABLE decisions ADD COLUMN IF NOT EXISTS owner_type VARCHAR(20)")
    op.execute("ALTER TABLE decisions ADD COLUMN IF NOT EXISTS decision_maker_type VARCHAR(20)")
    op.execute("UPDATE decisions SET owner_type = 'user' WHERE owner_type IS NULL")
    op.execute("UPDATE decisions SET decision_maker_type = 'user' WHERE decision_maker_type IS NULL AND decision_maker_id IS NOT NULL")
    op.execute("ALTER TABLE decisions ALTER COLUMN owner_type SET NOT NULL")
    op.execute("ALTER TABLE decisions DROP CONSTRAINT IF EXISTS decisions_owner_id_fkey")
    op.execute("ALTER TABLE decisions DROP CONSTRAINT IF EXISTS decisions_decision_maker_id_fkey")
    op.execute("ALTER TABLE decisions DROP CONSTRAINT IF EXISTS ck_owner_principal")
    op.execute("ALTER TABLE decisions DROP CONSTRAINT IF EXISTS ck_decision_maker_principal")
    op.execute(f"ALTER TABLE decisions ADD CONSTRAINT ck_owner_principal CHECK (owner_type IN ({_TYPES}))")
    op.execute(
        "ALTER TABLE decisions ADD CONSTRAINT ck_decision_maker_principal CHECK "
        f"((decision_maker_type IS NULL OR decision_maker_type IN ({_TYPES})) "
        "AND (decision_maker_type IS NULL) = (decision_maker_id IS NULL))"
    )


def downgrade() -> None:
    # Lossy: the type columns go, and the user foreign keys are not restored because a row
    # owned by a group has no user to point at.
    op.execute("ALTER TABLE decisions DROP CONSTRAINT IF EXISTS ck_owner_principal")
    op.execute("ALTER TABLE decisions DROP CONSTRAINT IF EXISTS ck_decision_maker_principal")
    op.execute("ALTER TABLE decisions DROP COLUMN IF EXISTS owner_type")
    op.execute("ALTER TABLE decisions DROP COLUMN IF EXISTS decision_maker_type")
