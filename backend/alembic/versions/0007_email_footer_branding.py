"""Email footer branding

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-16

Adds `email_footer_company_name` / `email_footer_website` / `email_footer_address` to both
`organizations` and `server_settings`. See the `Organization`/`ServerSettings` docstrings in
`app/models/organization.py` for the fields and `app/services/email_branding.py` for how they resolve.

`IF NOT EXISTS`, as in 0002.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE organizations ADD COLUMN IF NOT EXISTS email_footer_company_name VARCHAR(255)")
    op.execute("ALTER TABLE organizations ADD COLUMN IF NOT EXISTS email_footer_website VARCHAR(500)")
    op.execute("ALTER TABLE organizations ADD COLUMN IF NOT EXISTS email_footer_address TEXT")
    op.execute("ALTER TABLE server_settings ADD COLUMN IF NOT EXISTS email_footer_company_name VARCHAR(255)")
    op.execute("ALTER TABLE server_settings ADD COLUMN IF NOT EXISTS email_footer_website VARCHAR(500)")
    op.execute("ALTER TABLE server_settings ADD COLUMN IF NOT EXISTS email_footer_address TEXT")


def downgrade() -> None:
    op.execute("ALTER TABLE server_settings DROP COLUMN IF EXISTS email_footer_address")
    op.execute("ALTER TABLE server_settings DROP COLUMN IF EXISTS email_footer_website")
    op.execute("ALTER TABLE server_settings DROP COLUMN IF EXISTS email_footer_company_name")
    op.execute("ALTER TABLE organizations DROP COLUMN IF EXISTS email_footer_address")
    op.execute("ALTER TABLE organizations DROP COLUMN IF EXISTS email_footer_website")
    op.execute("ALTER TABLE organizations DROP COLUMN IF EXISTS email_footer_company_name")
