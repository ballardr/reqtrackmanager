"""Pain Point, Guiding Principle and Open Question owners become principals (users and groups on parity, Phase 4)

Revision ID: 0078
Revises: 0077
Create Date: 2026-10-12

`pain_points.owner_id`, `guiding_principle_versions.owner_id` and
`open_questions.owner_id` may now name a user, an organisation group or a
project group (docs/plans/users-and-groups-parity-plan.md). Each gets an
`owner_type` column (existing rows backfill to `user`), the foreign key to
`users` is dropped (the id now points at one of three tables; the service
validates it), and a check constraint keeps the pair consistent. Every
Guiding Principle version row is backfilled, not only the current one, so
history keeps who owned each version.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0078"
down_revision: str | None = "0077"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TYPES = "'user', 'org_group', 'project_group'"

# Tables whose optional `owner` field becomes a principal.
_TABLES = ("pain_points", "guiding_principle_versions", "open_questions")


def upgrade() -> None:
    for table in _TABLES:
        op.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS owner_type VARCHAR(20)")
        op.execute(f"UPDATE {table} SET owner_type = 'user' WHERE owner_type IS NULL AND owner_id IS NOT NULL")
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {table}_owner_id_fkey")
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS ck_owner_principal")
        op.execute(
            f"ALTER TABLE {table} ADD CONSTRAINT ck_owner_principal CHECK "
            f"((owner_type IS NULL OR owner_type IN ({_TYPES})) AND (owner_type IS NULL) = (owner_id IS NULL))"
        )


def downgrade() -> None:
    # Lossy: the type column goes, and the user foreign key is not restored because a row
    # owned by a group has no user to point at.
    for table in _TABLES:
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS ck_owner_principal")
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS owner_type")
