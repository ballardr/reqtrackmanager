"""Policy acknowledgement

Revision ID: 0156
Revises: 0155
Create Date: 2026-11-10

Adds `policy_documents.requires_acknowledgement` (off) and `policy_acknowledgements` (one row per person, policy and
published version, with a hash of the accepted text and the UTC time). Seeds nothing. Guarded so a database built from
the current models passes.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0156"
down_revision: str | None = "0155"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE policy_documents ADD COLUMN IF NOT EXISTS requires_acknowledgement BOOLEAN NOT NULL DEFAULT false")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS policy_acknowledgements (
            id UUID PRIMARY KEY,
            policy_id UUID NOT NULL REFERENCES policy_documents(id) ON DELETE CASCADE,
            version INTEGER NOT NULL,
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            content_hash VARCHAR(64) NOT NULL,
            acknowledged_at TIMESTAMP WITH TIME ZONE NOT NULL,
            CONSTRAINT uq_policy_acknowledgements_policy_version_user UNIQUE (policy_id, version, user_id)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_policy_acknowledgements_policy_id ON policy_acknowledgements (policy_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_policy_acknowledgements_user_id ON policy_acknowledgements (user_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS policy_acknowledgements")
    op.execute("ALTER TABLE policy_documents DROP COLUMN IF EXISTS requires_acknowledgement")
