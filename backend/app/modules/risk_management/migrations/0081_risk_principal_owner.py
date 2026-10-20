"""Risk owners become principals (users and groups on parity, Risk 5b)

Revision ID: 0081
Revises: 0080
Create Date: 2026-10-12

`risk_versions.owner_id` may now name a user, an organisation group or a
project group. It gets an
`owner_type` column (existing rows backfill to `user`), the foreign key to
`users` is dropped (the id now points at one of three tables; the service
validates it), and a check constraint keeps the pair consistent. Every version
row is backfilled, not only the current one, so history keeps who owned each
version.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0081"
down_revision: str | None = "0080"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TYPES = "'user', 'org_group', 'project_group'"


def upgrade() -> None:
    op.execute("ALTER TABLE risk_versions ADD COLUMN IF NOT EXISTS owner_type VARCHAR(20)")
    op.execute("UPDATE risk_versions SET owner_type = 'user' WHERE owner_type IS NULL AND owner_id IS NOT NULL")
    op.execute("ALTER TABLE risk_versions DROP CONSTRAINT IF EXISTS risk_versions_owner_id_fkey")
    op.execute("ALTER TABLE risk_versions DROP CONSTRAINT IF EXISTS ck_owner_principal")
    op.execute(
        f"ALTER TABLE risk_versions ADD CONSTRAINT ck_owner_principal CHECK "
        f"((owner_type IS NULL OR owner_type IN ({_TYPES})) AND (owner_type IS NULL) = (owner_id IS NULL))"
    )


def downgrade() -> None:
    # Lossy: the type column goes, and the user foreign key is not restored because a row
    # owned by a group has no user to point at.
    op.execute("ALTER TABLE risk_versions DROP CONSTRAINT IF EXISTS ck_owner_principal")
    op.execute("ALTER TABLE risk_versions DROP COLUMN IF EXISTS owner_type")
