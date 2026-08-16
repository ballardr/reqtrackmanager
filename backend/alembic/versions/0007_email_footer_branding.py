"""Email footer branding

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-16

Adds `email_footer_company_name` / `email_footer_website` /
`email_footer_address` to both `organizations` and `server_settings`. These
were added to the model classes in the "Added a html template system"
change but no migration was ever written for them, so any database that
went through a real Alembic upgrade (rather than `create_all()` on a fresh
schema) is missing these columns — see
`app/models/organization.py::Organization`/`ServerSettings` docstrings for
what the fields are for and `app/services/email_branding.py` for how
they're resolved.

`IF NOT EXISTS`, same reason 0002-0006 use it: a brand-new database's
`create_all()` already creates these columns against the current model
class, so a plain `ADD COLUMN` would fail there with "already exists"; an
already-migrated database from before this revision is genuinely missing
them.
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
