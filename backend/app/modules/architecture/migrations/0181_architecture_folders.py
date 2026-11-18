"""System Architecture folders

Revision ID: 0181
Revises: 0180
Create Date: 2026-11-14

Adds `architecture_folders` (a tree per kind that organises the elements, connections and diagrams lists; the
organisation owns element folders only) and a nullable `folder_id` on the three record tables. A record with no folder
is at the top level, so existing records are unchanged. Nothing is seeded.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0181"
down_revision: str | None = "0180"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_RECORD_TABLES = ("architecture_elements", "architecture_connections", "architecture_diagrams")


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS architecture_folders (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
            organization_id UUID REFERENCES organizations(id) ON DELETE CASCADE,
            kind VARCHAR(20) NOT NULL,
            name VARCHAR(100) NOT NULL,
            parent_id UUID REFERENCES architecture_folders(id) ON DELETE SET NULL,
            sort_order INTEGER NOT NULL DEFAULT 0,
            creator_id UUID NOT NULL REFERENCES users(id),
            CONSTRAINT ck_architecture_folders_one_owner CHECK ((project_id IS NULL) <> (organization_id IS NULL)),
            CONSTRAINT ck_architecture_folders_org_elements_only CHECK (organization_id IS NULL OR kind = 'element'),
            CONSTRAINT ck_architecture_folders_not_own_parent CHECK (parent_id IS NULL OR parent_id <> id)
        )
        """
    )
    for column in ("project_id", "organization_id", "parent_id"):
        op.execute(f"CREATE INDEX IF NOT EXISTS ix_architecture_folders_{column} ON architecture_folders ({column})")
    for table in _RECORD_TABLES:
        op.execute(
            f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS folder_id UUID REFERENCES architecture_folders(id) ON DELETE SET NULL"
        )
        op.execute(f"CREATE INDEX IF NOT EXISTS ix_{table}_folder_id ON {table} (folder_id)")


def downgrade() -> None:
    for table in _RECORD_TABLES:
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS folder_id")
    op.execute("DROP TABLE IF EXISTS architecture_folders")
