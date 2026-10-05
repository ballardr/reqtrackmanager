"""Guiding Principle data model (Module 1 Phase 4)

Revision ID: 0053
Revises: 0052
Create Date: 2026-09-28

Adds the five tables backing Context & Strategy's Phase 4 data model
(docs/plans/module-01-context-and-strategy-plan.md Phase 4 — Guiding
Principles), a structural mirror of migration 0048's `strategies`/
`strategy_versions`/`strategy_comments`/`strategy_comment_files`/
`strategy_files` set (identity+version split, org/project `scope`
discriminator, Phase 0 Q4's full version-history requirement) for the
Guiding Principle artefact:

- `guiding_principles` (identity row: `scope` discriminator, exactly one of
  `organization_id`/`project_id` set, enforced by a CHECK constraint).
- `guiding_principle_versions` (temporal content snapshot — source overview
  §8.3's field set: `name`, `principle_statement`, `rationale`, `priority`,
  `status`, `owner_id` — no `type` field, no `time_horizon`/`expected_
  outcomes`/`constraints`/`measures_of_success` the way `strategy_versions`
  has).
- `guiding_principle_comments` / `guiding_principle_comment_files` /
  `guiding_principle_files` — this module's own module-local comment-thread
  and attachment tables, mirroring `strategy_comments`/`strategy_comment_
  files`/`strategy_files`.

No backfill needed — this is a brand-new artefact type with no pre-existing
rows anywhere.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0053"
down_revision: str | None = "0052"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS guiding_principles (
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
            CONSTRAINT ck_guiding_principles_scope_matches_owner CHECK (
                (scope = 'organization' AND organization_id IS NOT NULL AND project_id IS NULL) OR
                (scope = 'project' AND project_id IS NOT NULL AND organization_id IS NULL)
            )
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_guiding_principles_organization_id ON guiding_principles (organization_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_guiding_principles_project_id ON guiding_principles (project_id)")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS guiding_principle_versions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            guiding_principle_id UUID NOT NULL REFERENCES guiding_principles(id) ON DELETE CASCADE,
            version_number INTEGER NOT NULL,
            valid_from TIMESTAMPTZ NOT NULL,
            valid_to TIMESTAMPTZ,
            name VARCHAR(300) NOT NULL,
            principle_statement TEXT NOT NULL,
            rationale TEXT NOT NULL DEFAULT '',
            priority VARCHAR(20) NOT NULL DEFAULT 'medium',
            status VARCHAR(20) NOT NULL DEFAULT 'draft',
            owner_id UUID REFERENCES users(id),
            change_note TEXT NOT NULL DEFAULT '',
            created_by UUID NOT NULL REFERENCES users(id),
            created_at TIMESTAMPTZ NOT NULL,
            UNIQUE (guiding_principle_id, version_number)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_guiding_principle_versions_current ON guiding_principle_versions "
        "(guiding_principle_id) WHERE valid_to IS NULL"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS guiding_principle_comments (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            guiding_principle_id UUID NOT NULL REFERENCES guiding_principles(id) ON DELETE CASCADE,
            author_id UUID NOT NULL REFERENCES users(id),
            body TEXT NOT NULL,
            edited_at TIMESTAMPTZ
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS guiding_principle_comment_files (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            comment_id UUID NOT NULL REFERENCES guiding_principle_comments(id) ON DELETE CASCADE,
            file_id UUID NOT NULL REFERENCES file_assets(id) ON DELETE CASCADE,
            uploaded_by UUID NOT NULL REFERENCES users(id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_guiding_principle_comment_files_comment_id "
        "ON guiding_principle_comment_files (comment_id)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS guiding_principle_files (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            guiding_principle_id UUID NOT NULL REFERENCES guiding_principles(id) ON DELETE CASCADE,
            file_id UUID NOT NULL REFERENCES file_assets(id) ON DELETE CASCADE,
            linked_by UUID NOT NULL REFERENCES users(id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (guiding_principle_id, file_id)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS guiding_principle_files")
    op.execute("DROP TABLE IF EXISTS guiding_principle_comment_files")
    op.execute("DROP TABLE IF EXISTS guiding_principle_comments")
    op.execute("DROP TABLE IF EXISTS guiding_principle_versions")
    op.execute("DROP TABLE IF EXISTS guiding_principles")
