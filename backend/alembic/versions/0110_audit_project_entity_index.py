"""Index the audit trail by project and record id

Revision ID: 0110
Revises: 0109
Create Date: 2026-10-28

A record's change history reads a project's audit events by record id alone, because the events about one record can
carry different entity types. With only `(project_id, entity_type, created_at)` to use, the database read every event of
the project and filtered on the id (15 ms and growing with the trail, per activity request, in the capacity profile).
Guarded: a database built from the current models already has it.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0110"
down_revision: str | None = "0109"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE INDEX IF NOT EXISTS ix_audit_events_project_entity ON audit_events (project_id, entity_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_audit_events_project_entity")
