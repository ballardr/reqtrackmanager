"""Index the generic link events in the audit trail by the records they name

Revision ID: 0109
Revises: 0108
Create Date: 2026-10-27

A record's activity timeline lists the generic link events (`entity_type = 'artefact_link'`) that name it as source or
target, matching on the ids kept in `detail`. With no index on those the timeline read every link event of the project
and compared two JSON fields per row, so its cost grew with the project's total number of links (92,000 link events in
one project at 5,000 requirements). Two partial expression indexes make it a lookup. Guarded: a database built from the
current models already has them.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0109"
down_revision: str | None = "0108"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_audit_events_link_source ON audit_events ((detail ->> 'source_id')) "
        "WHERE entity_type = 'artefact_link'"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_audit_events_link_target ON audit_events ((detail ->> 'target_id')) "
        "WHERE entity_type = 'artefact_link'"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_audit_events_link_target")
    op.execute("DROP INDEX IF EXISTS ix_audit_events_link_source")
