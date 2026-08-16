"""SCIM provisioning token

Revision ID: 0011
Revises: 0010
Create Date: 2026-08-16

Adds `organizations.scim_token_hash`/`scim_token_prefix` for inbound SCIM
2.0 provisioning (`routers/scim.py`) — a per-org bearer token, hashed the
same way as a Personal Access Token (`security.hash_pat`).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE organizations ADD COLUMN IF NOT EXISTS scim_token_hash VARCHAR(64)")
    op.execute("ALTER TABLE organizations ADD COLUMN IF NOT EXISTS scim_token_prefix VARCHAR(20)")


def downgrade() -> None:
    op.execute("ALTER TABLE organizations DROP COLUMN IF EXISTS scim_token_prefix")
    op.execute("ALTER TABLE organizations DROP COLUMN IF EXISTS scim_token_hash")
