"""Product Feedback data model

Revision ID: 0130
Revises: 0129
Create Date: 2026-11-04

Adds `enhancement_requests` / `enhancement_request_versions` (identity plus temporal content;
project- or organisation-owned), the module-local comment and attachment tables, and
`project_feedback_settings` (the per-project submission policy).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0130"
down_revision: str | None = "0129"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS enhancement_requests (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            scope VARCHAR(20) NOT NULL,
            organization_id UUID REFERENCES organizations(id) ON DELETE CASCADE,
            project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
            unique_code VARCHAR(64) NOT NULL,
            creator_id UUID NOT NULL REFERENCES users(id),
            is_archived BOOLEAN NOT NULL DEFAULT false,
            archived_at TIMESTAMPTZ,
            archived_by UUID REFERENCES users(id),
            CONSTRAINT uq_enhancement_requests_project_unique_code UNIQUE (project_id, unique_code),
            CONSTRAINT uq_enhancement_requests_organization_unique_code UNIQUE (organization_id, unique_code),
            CONSTRAINT ck_enhancement_requests_scope_matches_owner CHECK (
                (scope = 'organization' AND organization_id IS NOT NULL AND project_id IS NULL) OR
                (scope = 'project' AND project_id IS NOT NULL AND organization_id IS NULL)
            )
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_enhancement_requests_organization_id ON enhancement_requests (organization_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_enhancement_requests_project_id ON enhancement_requests (project_id)")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS enhancement_request_versions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            request_id UUID NOT NULL REFERENCES enhancement_requests(id) ON DELETE CASCADE,
            version_number INTEGER NOT NULL,
            valid_from TIMESTAMPTZ NOT NULL,
            valid_to TIMESTAMPTZ,
            title VARCHAR(300) NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            status VARCHAR(20) NOT NULL DEFAULT 'new',
            owner_type VARCHAR(20),
            owner_id UUID,
            external_ref_url VARCHAR(500),
            external_ref_key VARCHAR(100),
            decline_reason TEXT NOT NULL DEFAULT '',
            change_note TEXT NOT NULL DEFAULT '',
            created_by UUID NOT NULL REFERENCES users(id),
            created_at TIMESTAMPTZ NOT NULL,
            UNIQUE (request_id, version_number),
            CONSTRAINT ck_owner_principal CHECK (
                (owner_type IS NULL OR owner_type IN ('user', 'org_group', 'project_group'))
                AND (owner_type IS NULL) = (owner_id IS NULL)
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_enhancement_request_versions_current "
        "ON enhancement_request_versions (request_id) WHERE valid_to IS NULL"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS enhancement_request_comments (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            request_id UUID NOT NULL REFERENCES enhancement_requests(id) ON DELETE CASCADE,
            author_id UUID NOT NULL REFERENCES users(id),
            body TEXT NOT NULL,
            edited_at TIMESTAMPTZ
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS enhancement_request_comment_files (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            comment_id UUID NOT NULL REFERENCES enhancement_request_comments(id) ON DELETE CASCADE,
            file_id UUID NOT NULL REFERENCES file_assets(id) ON DELETE CASCADE,
            uploaded_by UUID NOT NULL REFERENCES users(id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_enhancement_request_comment_files_comment_id "
        "ON enhancement_request_comment_files (comment_id)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS enhancement_request_files (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            request_id UUID NOT NULL REFERENCES enhancement_requests(id) ON DELETE CASCADE,
            file_id UUID NOT NULL REFERENCES file_assets(id) ON DELETE CASCADE,
            linked_by UUID NOT NULL REFERENCES users(id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (request_id, file_id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS project_feedback_settings (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            project_id UUID NOT NULL UNIQUE REFERENCES projects(id) ON DELETE CASCADE,
            submission_policy VARCHAR(20) NOT NULL DEFAULT 'members'
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS project_feedback_settings")
    op.execute("DROP TABLE IF EXISTS enhancement_request_files")
    op.execute("DROP TABLE IF EXISTS enhancement_request_comment_files")
    op.execute("DROP TABLE IF EXISTS enhancement_request_comments")
    op.execute("DROP TABLE IF EXISTS enhancement_request_versions")
    op.execute("DROP TABLE IF EXISTS enhancement_requests")
