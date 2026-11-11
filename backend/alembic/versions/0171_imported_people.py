"""Imported people: `users.imported_organization_id`, `users.imported_key` and `organizations.imported_person_retention_days`.

Revision ID: 0171
Revises: 0170
Create Date: 2026-11-11

An imported person is an inactive, archived user row standing in for someone named in a bundle who is not a member of the
target organisation. A partial unique index keeps one stand-in per organisation and keyed email hash. Guarded so a
database built from the current models passes.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0171"
down_revision: str | None = "0170"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS imported_organization_id UUID")
    op.execute(
        "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_users_imported_organization_id') THEN "
        "ALTER TABLE users ADD CONSTRAINT fk_users_imported_organization_id FOREIGN KEY (imported_organization_id) "
        "REFERENCES organizations(id) ON DELETE RESTRICT; END IF; END $$"
    )
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS imported_key VARCHAR(64)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_users_imported_organization_id ON users (imported_organization_id)")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_users_imported_org_key ON users (imported_organization_id, imported_key) "
        "WHERE imported_organization_id IS NOT NULL"
    )
    op.execute("ALTER TABLE organizations ADD COLUMN IF NOT EXISTS imported_person_retention_days INTEGER")


def downgrade() -> None:
    op.execute("ALTER TABLE organizations DROP COLUMN IF EXISTS imported_person_retention_days")
    op.execute("DROP INDEX IF EXISTS uq_users_imported_org_key")
    op.execute("DROP INDEX IF EXISTS ix_users_imported_organization_id")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS imported_key")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS imported_organization_id")
