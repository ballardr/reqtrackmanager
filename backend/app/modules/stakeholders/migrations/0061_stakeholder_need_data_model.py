"""Stakeholder Need data model (Module 2 Phase 2)

Revision ID: 0061
Revises: 0060
Create Date: 2026-10-05

Adds the project-scoped Stakeholder Need tables (docs/plans/module-02-
stakeholders-and-personas-plan.md Phase 2): `stakeholder_needs`/
`stakeholder_need_versions` (identity + temporal content) and the module-local
comment/attachment tables. "Has need" and "gives rise to" relationships are
`artefact_links` rows, so need no table of their own.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0061"
down_revision: str | None = "0060"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS stakeholder_needs (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            creator_id UUID NOT NULL REFERENCES users(id),
            is_archived BOOLEAN NOT NULL DEFAULT false,
            archived_at TIMESTAMPTZ,
            archived_by UUID REFERENCES users(id)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_stakeholder_needs_project_id ON stakeholder_needs (project_id)")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS stakeholder_need_versions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            need_id UUID NOT NULL REFERENCES stakeholder_needs(id) ON DELETE CASCADE,
            version_number INTEGER NOT NULL,
            valid_from TIMESTAMPTZ NOT NULL,
            valid_to TIMESTAMPTZ,
            name VARCHAR(300) NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            rationale TEXT NOT NULL DEFAULT '',
            status VARCHAR(20) NOT NULL DEFAULT 'draft',
            owner_id UUID REFERENCES users(id),
            change_note TEXT NOT NULL DEFAULT '',
            created_by UUID NOT NULL REFERENCES users(id),
            created_at TIMESTAMPTZ NOT NULL,
            UNIQUE (need_id, version_number)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_stakeholder_need_versions_current ON stakeholder_need_versions (need_id) "
        "WHERE valid_to IS NULL"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS stakeholder_need_comments (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            need_id UUID NOT NULL REFERENCES stakeholder_needs(id) ON DELETE CASCADE,
            author_id UUID NOT NULL REFERENCES users(id),
            body TEXT NOT NULL,
            edited_at TIMESTAMPTZ
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS stakeholder_need_comment_files (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            comment_id UUID NOT NULL REFERENCES stakeholder_need_comments(id) ON DELETE CASCADE,
            file_id UUID NOT NULL REFERENCES file_assets(id) ON DELETE CASCADE,
            uploaded_by UUID NOT NULL REFERENCES users(id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_stakeholder_need_comment_files_comment_id "
        "ON stakeholder_need_comment_files (comment_id)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS stakeholder_need_files (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            need_id UUID NOT NULL REFERENCES stakeholder_needs(id) ON DELETE CASCADE,
            file_id UUID NOT NULL REFERENCES file_assets(id) ON DELETE CASCADE,
            linked_by UUID NOT NULL REFERENCES users(id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (need_id, file_id)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS stakeholder_need_files")
    op.execute("DROP TABLE IF EXISTS stakeholder_need_comment_files")
    op.execute("DROP TABLE IF EXISTS stakeholder_need_comments")
    op.execute("DROP TABLE IF EXISTS stakeholder_need_versions")
    op.execute("DROP TABLE IF EXISTS stakeholder_needs")
