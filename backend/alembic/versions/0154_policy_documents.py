"""Policy documents

Revision ID: 0154
Revises: 0153
Create Date: 2026-11-09

Adds `policy_documents` (a policy and its working copy; a NULL organisation is a server policy) and the
append-only `policy_document_versions`. Seeds nothing: a policy exists once an administrator writes it. Guarded so
a database built from the current models passes.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0154"
down_revision: str | None = "0153"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS policy_documents (
            id UUID PRIMARY KEY,
            organization_id UUID REFERENCES organizations(id) ON DELETE CASCADE,
            key VARCHAR(20),
            title VARCHAR(120) NOT NULL,
            body JSONB NOT NULL DEFAULT '{}'::jsonb,
            state VARCHAR(20) NOT NULL DEFAULT 'draft',
            effective_from DATE,
            current_version INTEGER NOT NULL DEFAULT 0,
            created_by UUID REFERENCES users(id) ON DELETE SET NULL,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_policy_documents_organization_id ON policy_documents (organization_id)")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_policy_documents_server_key ON policy_documents (key) "
        "WHERE organization_id IS NULL AND key IS NOT NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_policy_documents_org_key ON policy_documents (organization_id, key) "
        "WHERE organization_id IS NOT NULL AND key IS NOT NULL"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS policy_document_versions (
            id UUID PRIMARY KEY,
            policy_id UUID NOT NULL REFERENCES policy_documents(id) ON DELETE CASCADE,
            version INTEGER NOT NULL,
            title VARCHAR(120) NOT NULL,
            body JSONB NOT NULL,
            effective_from DATE,
            published_at TIMESTAMPTZ NOT NULL,
            published_by UUID REFERENCES users(id) ON DELETE SET NULL,
            change_note TEXT NOT NULL DEFAULT '',
            CONSTRAINT uq_policy_document_versions_policy_version UNIQUE (policy_id, version)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_policy_document_versions_policy_id ON policy_document_versions (policy_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS policy_document_versions")
    op.execute("DROP TABLE IF EXISTS policy_documents")
