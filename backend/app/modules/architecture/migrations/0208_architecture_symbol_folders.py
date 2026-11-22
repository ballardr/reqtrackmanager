"""System Architecture: folders for the symbol library

Revision ID: 0208
Revises: 0207
Create Date: 2026-11-23

Adds `architecture_symbols.folder_id` (the folder of the owner's `symbol` tree a symbol is filed in; no symbol is filed
on upgrade, so every symbol stays at the top level) and lets the organisation own folders of the `symbol` kind as well as
the `element` kind (`ck_architecture_folders_org_kinds` replaces `ck_architecture_folders_org_elements_only`). It also
makes `architecture_symbols.file_asset_id` cascade: `SET NULL` could never succeed (the row would then have no source,
which `ck_architecture_symbols_one_source` forbids), so deleting an organisation that held an uploaded symbol failed.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0208"
down_revision: str | None = "0207"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE architecture_symbols DROP CONSTRAINT IF EXISTS architecture_symbols_file_asset_id_fkey")
    op.execute(
        "ALTER TABLE architecture_symbols ADD CONSTRAINT architecture_symbols_file_asset_id_fkey "
        "FOREIGN KEY (file_asset_id) REFERENCES file_assets(id) ON DELETE CASCADE"
    )
    op.execute(
        "ALTER TABLE architecture_symbols ADD COLUMN IF NOT EXISTS folder_id UUID "
        "REFERENCES architecture_folders(id) ON DELETE SET NULL"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_architecture_symbols_folder_id ON architecture_symbols (folder_id)")
    op.execute("ALTER TABLE architecture_folders DROP CONSTRAINT IF EXISTS ck_architecture_folders_org_elements_only")
    op.execute("ALTER TABLE architecture_folders DROP CONSTRAINT IF EXISTS ck_architecture_folders_org_kinds")
    op.execute(
        "ALTER TABLE architecture_folders ADD CONSTRAINT ck_architecture_folders_org_kinds "
        "CHECK (organization_id IS NULL OR kind IN ('element', 'symbol'))"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE architecture_folders DROP CONSTRAINT IF EXISTS ck_architecture_folders_org_kinds")
    op.execute("DELETE FROM architecture_folders WHERE organization_id IS NOT NULL AND kind <> 'element'")
    op.execute(
        "ALTER TABLE architecture_folders ADD CONSTRAINT ck_architecture_folders_org_elements_only "
        "CHECK (organization_id IS NULL OR kind = 'element')"
    )
    op.execute("ALTER TABLE architecture_symbols DROP CONSTRAINT IF EXISTS architecture_symbols_file_asset_id_fkey")
    op.execute(
        "ALTER TABLE architecture_symbols ADD CONSTRAINT architecture_symbols_file_asset_id_fkey "
        "FOREIGN KEY (file_asset_id) REFERENCES file_assets(id) ON DELETE SET NULL"
    )
    op.execute("DROP INDEX IF EXISTS ix_architecture_symbols_folder_id")
    op.execute("ALTER TABLE architecture_symbols DROP COLUMN IF EXISTS folder_id")
