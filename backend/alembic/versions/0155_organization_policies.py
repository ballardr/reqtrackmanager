"""Organisation policies

Revision ID: 0155
Revises: 0154
Create Date: 2026-11-10

Adds `policy_audience` (the users and organisation groups an organisation policy is limited to; no rows means every
member) and `organizations.allow_policy_links` (whether an organisation's policies may contain links; off). Seeds
nothing. Guarded so a database built from the current models passes.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0155"
down_revision: str | None = "0154"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE organizations ADD COLUMN IF NOT EXISTS allow_policy_links BOOLEAN NOT NULL DEFAULT false")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS policy_audience (
            id UUID PRIMARY KEY,
            policy_id UUID NOT NULL REFERENCES policy_documents(id) ON DELETE CASCADE,
            audience_type VARCHAR(20) NOT NULL,
            audience_id UUID NOT NULL,
            CONSTRAINT uq_policy_audience UNIQUE (policy_id, audience_type, audience_id),
            CONSTRAINT ck_audience_principal CHECK (audience_type IN ('user', 'org_group', 'project_group'))
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_policy_audience_policy_id ON policy_audience (policy_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS policy_audience")
    op.execute("ALTER TABLE organizations DROP COLUMN IF EXISTS allow_policy_links")
