"""`footer_position` on `server_settings` and `organizations`: where the footer of the signed-out pages sits.

Revision ID: 0170
Revises: 0169
Create Date: 2026-11-11

The platform value is `after_content` on every existing row (the layout before the setting existed); an organisation's
value is null, which follows the platform. Guarded so a database built from the current models passes.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0170"
down_revision: str | None = "0169"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE server_settings ADD COLUMN IF NOT EXISTS footer_position VARCHAR(20) NOT NULL DEFAULT 'after_content'")
    op.execute("ALTER TABLE organizations ADD COLUMN IF NOT EXISTS footer_position VARCHAR(20)")


def downgrade() -> None:
    op.execute("ALTER TABLE organizations DROP COLUMN IF EXISTS footer_position")
    op.execute("ALTER TABLE server_settings DROP COLUMN IF EXISTS footer_position")
