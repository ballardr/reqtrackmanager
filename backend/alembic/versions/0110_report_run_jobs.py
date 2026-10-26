"""Background custom report runs: job state, stored output and the organisation retention setting

Revision ID: 0110
Revises: 0109
Create Date: 2026-10-27

Adds the job columns of `generated_reports` (`status`, `started_at`, `finished_at`, `expires_at`,
`output_key`, `output_filename`, `output_size`, `error`) and `organizations.report_output_retention_days`.
Existing rows are synchronous runs, so they take the `completed` status. Guarded: a database built from the
current models has them.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0110"
down_revision: str | None = "0109"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE generated_reports ADD COLUMN IF NOT EXISTS status VARCHAR(12) NOT NULL DEFAULT 'completed'")
    op.execute("ALTER TABLE generated_reports ADD COLUMN IF NOT EXISTS started_at TIMESTAMPTZ")
    op.execute("ALTER TABLE generated_reports ADD COLUMN IF NOT EXISTS finished_at TIMESTAMPTZ")
    op.execute("ALTER TABLE generated_reports ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ")
    op.execute("ALTER TABLE generated_reports ADD COLUMN IF NOT EXISTS output_key VARCHAR(300)")
    op.execute("ALTER TABLE generated_reports ADD COLUMN IF NOT EXISTS output_filename VARCHAR(300)")
    op.execute("ALTER TABLE generated_reports ADD COLUMN IF NOT EXISTS output_size INTEGER")
    op.execute("ALTER TABLE generated_reports ADD COLUMN IF NOT EXISTS error VARCHAR(500)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_generated_reports_status ON generated_reports (status)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_generated_reports_expires_at ON generated_reports (expires_at)")
    op.execute("ALTER TABLE organizations ADD COLUMN IF NOT EXISTS report_output_retention_days INTEGER")


def downgrade() -> None:
    op.execute("ALTER TABLE organizations DROP COLUMN IF EXISTS report_output_retention_days")
    op.execute("DROP INDEX IF EXISTS ix_generated_reports_expires_at")
    op.execute("DROP INDEX IF EXISTS ix_generated_reports_status")
    for column in ("error", "output_size", "output_filename", "output_key", "expires_at", "finished_at", "started_at", "status"):
        op.execute(f"ALTER TABLE generated_reports DROP COLUMN IF EXISTS {column}")
