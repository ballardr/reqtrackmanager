"""A project's report-image library: file_assets.project_id

Revision ID: 0117
Revises: 0116
Create Date: 2026-10-30

Adds the nullable `file_assets.project_id`, set only for a picture in a project's own report-image library. Guarded: a
database built from the current models already has it.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0117"
down_revision: str | None = "0116"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE file_assets ADD COLUMN IF NOT EXISTS project_id UUID REFERENCES projects(id) ON DELETE CASCADE")
    op.execute("CREATE INDEX IF NOT EXISTS ix_file_assets_project_id ON file_assets (project_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_file_assets_project_id")
    op.execute("ALTER TABLE file_assets DROP COLUMN IF EXISTS project_id")
