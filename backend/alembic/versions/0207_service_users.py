"""Service users: `users.is_service_account`, `service_user_profiles` and `personal_access_tokens.created_by_user_id`.

Revision ID: 0207
Revises: 0206
Create Date: 2026-11-21

Nothing is backfilled: every existing account is an ordinary user and every existing token was created by its owner (the
column stays null and reads as the owner). Guarded so a database built from the current models passes.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0207"
down_revision: str | None = "0206"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_service_account BOOLEAN NOT NULL DEFAULT false")
    op.execute(
        "ALTER TABLE personal_access_tokens ADD COLUMN IF NOT EXISTS created_by_user_id UUID "
        "REFERENCES users(id) ON DELETE SET NULL"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS service_user_profiles (
            id UUID PRIMARY KEY,
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            description VARCHAR(500) NOT NULL DEFAULT '',
            responsible_type VARCHAR(20),
            responsible_id UUID,
            created_by UUID REFERENCES users(id) ON DELETE SET NULL,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            CONSTRAINT ck_responsible_principal CHECK (
                (responsible_type IS NULL OR responsible_type IN ('user', 'org_group', 'project_group'))
                AND (responsible_type IS NULL) = (responsible_id IS NULL)
            )
        )
        """
    )
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_service_user_profiles_user_id ON service_user_profiles (user_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_service_user_profiles_organization_id ON service_user_profiles (organization_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS service_user_profiles")
    op.execute("ALTER TABLE personal_access_tokens DROP COLUMN IF EXISTS created_by_user_id")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS is_service_account")
