"""Credential reset: reset tokens and the must-reset marker

Revision ID: 0106
Revises: 0105
Create Date: 2026-10-24

Adds `credential_reset_tokens` (hashed, single-use, expiring password-reset secrets) and
`users.must_reset_credentials` (set by a forced reset; blocks native sign-in until the person
chooses a new password). The credential epoch is the existing `users.token_version`. Guarded: a
database built from the current models already has both.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0106"
down_revision: str | None = "0105"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS must_reset_credentials BOOLEAN NOT NULL DEFAULT false")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS credential_reset_tokens (
            id UUID PRIMARY KEY,
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            token_hash VARCHAR(64) NOT NULL,
            issued_via VARCHAR(20) NOT NULL,
            issued_by UUID REFERENCES users(id) ON DELETE SET NULL,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL,
            expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
            used_at TIMESTAMP WITH TIME ZONE
        )
        """
    )
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_credential_reset_tokens_token_hash ON credential_reset_tokens (token_hash)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_credential_reset_tokens_user_id ON credential_reset_tokens (user_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS credential_reset_tokens")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS must_reset_credentials")
