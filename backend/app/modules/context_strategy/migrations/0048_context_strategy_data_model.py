"""Context & Strategy data model (Module 1 Phase 1)

Revision ID: 0048
Revises: 0047
Create Date: 2026-09-28

Adds the six tables backing Context & Strategy's Phase 1 data model
(docs/plans/module-01-context-and-strategy-plan.md Phase 1 — Organisation
& Project Strategy):

- `strategies` (identity row: `scope` discriminator, exactly one of
  `organization_id`/`project_id` set, enforced by a CHECK constraint).
- `strategy_versions` (temporal content snapshot, mirrors
  `requirement_versions` exactly).
- `strategy_comments` / `strategy_comment_files` / `strategy_files` — this
  module's own module-local comment-thread and attachment tables, mirroring
  migration 0045's `decision_comments`/`decision_comment_files`/
  `decision_files`.

No backfill needed — this is a brand-new artefact type with no pre-existing
rows anywhere.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0048"
down_revision: str | None = "0047"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS strategies (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            scope VARCHAR(20) NOT NULL,
            organization_id UUID REFERENCES organizations(id) ON DELETE CASCADE,
            project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
            creator_id UUID NOT NULL REFERENCES users(id),
            is_archived BOOLEAN NOT NULL DEFAULT false,
            archived_at TIMESTAMPTZ,
            archived_by UUID REFERENCES users(id),
            CONSTRAINT ck_strategies_scope_matches_owner CHECK (
                (scope = 'organization' AND organization_id IS NOT NULL AND project_id IS NULL) OR
                (scope = 'project' AND project_id IS NOT NULL AND organization_id IS NULL)
            )
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_strategies_organization_id ON strategies (organization_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_strategies_project_id ON strategies (project_id)")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS strategy_versions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            strategy_id UUID NOT NULL REFERENCES strategies(id) ON DELETE CASCADE,
            version_number INTEGER NOT NULL,
            valid_from TIMESTAMPTZ NOT NULL,
            valid_to TIMESTAMPTZ,
            title VARCHAR(300) NOT NULL,
            objective TEXT NOT NULL,
            current_state TEXT NOT NULL DEFAULT '',
            desired_future_state TEXT NOT NULL DEFAULT '',
            rationale TEXT NOT NULL DEFAULT '',
            expected_outcomes TEXT NOT NULL DEFAULT '',
            constraints TEXT NOT NULL DEFAULT '',
            measures_of_success TEXT NOT NULL DEFAULT '',
            priority VARCHAR(20) NOT NULL DEFAULT 'medium',
            time_horizon VARCHAR(20) NOT NULL DEFAULT 'medium_term',
            status VARCHAR(20) NOT NULL DEFAULT 'draft',
            change_note TEXT NOT NULL DEFAULT '',
            created_by UUID NOT NULL REFERENCES users(id),
            created_at TIMESTAMPTZ NOT NULL,
            UNIQUE (strategy_id, version_number)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_strategy_versions_current ON strategy_versions (strategy_id) "
        "WHERE valid_to IS NULL"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS strategy_comments (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            strategy_id UUID NOT NULL REFERENCES strategies(id) ON DELETE CASCADE,
            author_id UUID NOT NULL REFERENCES users(id),
            body TEXT NOT NULL,
            edited_at TIMESTAMPTZ
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS strategy_comment_files (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            comment_id UUID NOT NULL REFERENCES strategy_comments(id) ON DELETE CASCADE,
            file_id UUID NOT NULL REFERENCES file_assets(id) ON DELETE CASCADE,
            uploaded_by UUID NOT NULL REFERENCES users(id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_strategy_comment_files_comment_id ON strategy_comment_files (comment_id)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS strategy_files (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            strategy_id UUID NOT NULL REFERENCES strategies(id) ON DELETE CASCADE,
            file_id UUID NOT NULL REFERENCES file_assets(id) ON DELETE CASCADE,
            linked_by UUID NOT NULL REFERENCES users(id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (strategy_id, file_id)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS strategy_files")
    op.execute("DROP TABLE IF EXISTS strategy_comment_files")
    op.execute("DROP TABLE IF EXISTS strategy_comments")
    op.execute("DROP TABLE IF EXISTS strategy_versions")
    op.execute("DROP TABLE IF EXISTS strategies")
