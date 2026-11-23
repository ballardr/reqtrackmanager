"""Self-signup, sso_only enforcement follow-on, and external project users

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-09

Adds `ServerSettings.signup_mode`; three `Organization` columns (`allow_self_signup`,
`auto_accept_email_domain`, `external_user_policy`); and the `pending_invites` table (see
docs/decisions.md's "Self-signup, invites, and SSO" entry).

Every statement is `IF NOT EXISTS`/`IF EXISTS`: on a new database 0001's `create_all()` already
creates these columns from the current models, while an already-migrated database lacks them, so the
statements converge to the same end state in both cases.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE server_settings ADD COLUMN IF NOT EXISTS signup_mode VARCHAR(30) NOT NULL DEFAULT 'disabled'"
    )
    op.execute(
        "ALTER TABLE organizations ADD COLUMN IF NOT EXISTS allow_self_signup BOOLEAN NOT NULL DEFAULT false"
    )
    op.execute("ALTER TABLE organizations ADD COLUMN IF NOT EXISTS auto_accept_email_domain VARCHAR(255)")
    op.execute(
        "ALTER TABLE organizations ADD COLUMN IF NOT EXISTS external_user_policy VARCHAR(30) NOT NULL DEFAULT 'disabled'"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS pending_invites (
            id UUID PRIMARY KEY,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            email VARCHAR(255) NOT NULL,
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
            project_role VARCHAR(30),
            invited_by UUID NOT NULL REFERENCES users(id),
            token VARCHAR(64) NOT NULL,
            expires_at TIMESTAMPTZ NOT NULL,
            accepted_at TIMESTAMPTZ
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_pending_invites_email ON pending_invites (email)")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_pending_invites_token ON pending_invites (token)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS pending_invites")
    op.execute("ALTER TABLE organizations DROP COLUMN IF EXISTS external_user_policy")
    op.execute("ALTER TABLE organizations DROP COLUMN IF EXISTS auto_accept_email_domain")
    op.execute("ALTER TABLE organizations DROP COLUMN IF EXISTS allow_self_signup")
    op.execute("ALTER TABLE server_settings DROP COLUMN IF EXISTS signup_mode")
