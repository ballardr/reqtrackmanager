"""`organizations.oidc_allow_account_creation`: whether the organisation's identity provider may create new accounts.

Revision ID: 0166
Revises: 0165
Create Date: 2026-11-10

Default true, so an upgrade changes nothing. Guarded so a database built from the current models passes.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0166"
down_revision: str | None = "0165"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE organizations ADD COLUMN IF NOT EXISTS oidc_allow_account_creation BOOLEAN NOT NULL DEFAULT true")


def downgrade() -> None:
    op.execute("ALTER TABLE organizations DROP COLUMN IF EXISTS oidc_allow_account_creation")
