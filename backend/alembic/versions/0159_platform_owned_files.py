"""Platform-owned files

Revision ID: 0159
Revises: 0158
Create Date: 2026-11-10

`file_assets.organization_id` becomes nullable: the platform logo and login background belong to no organisation, so deleting
an organisation, its storage limit and its upload switch can no longer remove or refuse them. Existing platform files, which
were stored against whichever organisation existed first, are detached from it. Guarded so a database built from the current
models passes.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0159"
down_revision: str | None = "0158"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE file_assets ALTER COLUMN organization_id DROP NOT NULL")
    op.execute(
        "UPDATE file_assets SET organization_id = NULL WHERE id IN ("
        "SELECT default_logo_file_id FROM server_settings WHERE default_logo_file_id IS NOT NULL "
        "UNION SELECT default_login_background_file_id FROM server_settings WHERE default_login_background_file_id IS NOT NULL)"
    )


def downgrade() -> None:
    # A platform-owned file is re-attached to the oldest organisation, as before this revision; with none, the row is removed.
    op.execute(
        "UPDATE server_settings SET default_logo_file_id = NULL, default_login_background_file_id = NULL "
        "WHERE NOT EXISTS (SELECT 1 FROM organizations)"
    )
    op.execute("DELETE FROM file_assets WHERE organization_id IS NULL AND NOT EXISTS (SELECT 1 FROM organizations)")
    op.execute(
        "UPDATE file_assets SET organization_id = (SELECT id FROM organizations ORDER BY created_at LIMIT 1) "
        "WHERE organization_id IS NULL"
    )
    op.execute("ALTER TABLE file_assets ALTER COLUMN organization_id SET NOT NULL")
