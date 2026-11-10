"""Organisation file upload switch, storage limit and the server default limit

Revision ID: 0158
Revises: 0157
Create Date: 2026-11-10

Adds `organizations.file_uploads_enabled` (on), `organizations.storage_quota_bytes` (null: use the server default),
`organizations.storage_warned` (the 90% notice was sent) and `server_settings.default_storage_quota_bytes` (null: no
limit), so an upgrade changes nothing. Seeds nothing. Guarded so a database built from the current models passes.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0158"
down_revision: str | None = "0157"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE organizations ADD COLUMN IF NOT EXISTS file_uploads_enabled BOOLEAN NOT NULL DEFAULT true")
    op.execute("ALTER TABLE organizations ADD COLUMN IF NOT EXISTS storage_quota_bytes BIGINT")
    op.execute("ALTER TABLE organizations ADD COLUMN IF NOT EXISTS storage_warned BOOLEAN NOT NULL DEFAULT false")
    op.execute("ALTER TABLE server_settings ADD COLUMN IF NOT EXISTS default_storage_quota_bytes BIGINT")
    op.execute("CREATE INDEX IF NOT EXISTS ix_file_assets_organization_id ON file_assets (organization_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_file_assets_organization_id")
    op.execute("ALTER TABLE server_settings DROP COLUMN IF EXISTS default_storage_quota_bytes")
    op.execute("ALTER TABLE organizations DROP COLUMN IF EXISTS storage_warned")
    op.execute("ALTER TABLE organizations DROP COLUMN IF EXISTS storage_quota_bytes")
    op.execute("ALTER TABLE organizations DROP COLUMN IF EXISTS file_uploads_enabled")
