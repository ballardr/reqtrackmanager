"""Index the audit trail by record and by project

Revision ID: 0108
Revises: 0107
Create Date: 2026-10-27

`audit_events` grows with every write and had no index besides its key, so a record's activity timeline, a project's
change feed and the `SET NULL` of a deleted project each scanned the whole trail (three sequential scans per activity
request in the PostgreSQL profile, 8-11 ms each at 1,000 requirements per project and growing with the trail). Guarded: a
database built from the current models already has them.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0108"
down_revision: str | None = "0107"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE INDEX IF NOT EXISTS ix_audit_events_entity ON audit_events (entity_type, entity_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_audit_events_project_type ON audit_events (project_id, entity_type, created_at)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_audit_events_project_type")
    op.execute("DROP INDEX IF EXISTS ix_audit_events_entity")
