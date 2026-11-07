"""Announcements

Revision ID: 0148
Revises: 0147
Create Date: 2026-11-08

Adds `announcements`: scheduled plain-text messages, server-wide (NULL organisation) or per organisation, shown on
the login pages and as a banner after sign-in. Seeds nothing. Guarded so a database built from the current models
passes.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0148"
down_revision: str | None = "0147"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS announcements (
            id UUID PRIMARY KEY,
            organization_id UUID REFERENCES organizations(id) ON DELETE CASCADE,
            title VARCHAR(120) NOT NULL,
            body TEXT NOT NULL DEFAULT '',
            severity VARCHAR(20) NOT NULL DEFAULT 'information',
            starts_at TIMESTAMPTZ,
            ends_at TIMESTAMPTZ,
            show_on_login BOOLEAN NOT NULL DEFAULT FALSE,
            notified_at TIMESTAMPTZ,
            notified_count INTEGER,
            created_by UUID REFERENCES users(id) ON DELETE SET NULL,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_announcements_organization_id ON announcements (organization_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS announcements")
