"""Server-tier RBAC extension (module system Phase 0)

Revision ID: 0023
Revises: 0022
Create Date: 2026-09-04

Foundation for the modular feature system (docs/compliance-module-plan.md
Phase 0): a new `server_roles` table (`app.models.server_role.
UserServerRole`) granting a user a server-tier role beyond the existing
`User.is_server_admin` boolean, plus `server_settings.
default_module_entitlement_policy` for Phase 1's entitlement resolution.

`User.is_server_admin` is left completely untouched — this migration adds
new, additive columns/tables only, no backfill of existing data into the
new table (see `ServerRole`'s docstring for why `SERVER_ADMIN`-equivalent
power deliberately stays exclusively on that boolean).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS server_roles (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            role VARCHAR(30) NOT NULL,
            granted_by UUID REFERENCES users(id),
            UNIQUE (user_id, role)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_server_roles_user_id ON server_roles (user_id)")

    op.execute(
        "ALTER TABLE server_settings ADD COLUMN IF NOT EXISTS default_module_entitlement_policy "
        "VARCHAR(30) NOT NULL DEFAULT 'open'"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE server_settings DROP COLUMN IF EXISTS default_module_entitlement_policy")
    op.execute("DROP TABLE IF EXISTS server_roles")
