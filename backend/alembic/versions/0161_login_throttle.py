"""Progressive login delay: `login_events.kind` and the two indexes the delay reads.

Revision ID: 0161
Revises: 0160
Create Date: 2026-11-10

`kind` says which door an attempt used (`password`, `second_factor`, `sso`, `throttled`); only failed password attempts count towards the delay.
The indexes serve the per-account and per-address counts of recent failures. Guarded so a database built from the
current models passes.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0161"
down_revision: str | None = "0160"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE login_events ADD COLUMN IF NOT EXISTS kind VARCHAR(20) NOT NULL DEFAULT 'password'")
    op.execute("CREATE INDEX IF NOT EXISTS ix_login_events_email_created ON login_events (email_attempted, created_at)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_login_events_ip_created ON login_events (ip_address, created_at)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_login_events_ip_created")
    op.execute("DROP INDEX IF EXISTS ix_login_events_email_created")
    op.execute("ALTER TABLE login_events DROP COLUMN IF EXISTS kind")
