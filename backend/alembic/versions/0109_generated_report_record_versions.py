"""Record versions on custom report provenance rows

Revision ID: 0109
Revises: 0108
Create Date: 2026-10-26

Adds `generated_reports.record_versions` (`{type: {record id: version number}}` for the versioned records in
a report) and `record_versions_truncated`. Guarded: a database built from the current models has them.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0109"
down_revision: str | None = "0108"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE generated_reports ADD COLUMN IF NOT EXISTS record_versions JSONB NOT NULL DEFAULT '{}'")
    op.execute("ALTER TABLE generated_reports ADD COLUMN IF NOT EXISTS record_versions_truncated BOOLEAN NOT NULL DEFAULT false")


def downgrade() -> None:
    op.execute("ALTER TABLE generated_reports DROP COLUMN IF EXISTS record_versions_truncated")
    op.execute("ALTER TABLE generated_reports DROP COLUMN IF EXISTS record_versions")
