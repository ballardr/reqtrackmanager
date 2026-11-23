"""Future State data model

Revision ID: 0051
Revises: 0050
Create Date: 2026-09-28

Adds the five tables of the standalone Future State artefact, structurally mirroring migration 0048's strategy tables:

- `future_states`: the identity row (`scope` discriminator; a CHECK keeps exactly one of `organization_id` and
  `project_id`).
- `future_state_versions`: the temporal content snapshot (§7: `current_state`, `desired_state`, `target_date` as a DATE,
  `outcomes`, `success_measures`, `constraints`, `assumptions`, and a display `title` as `strategy_versions.title`).
- `future_state_comments`, `future_state_comment_files` and `future_state_files`: the module-local comment and attachment
  tables.

A new artefact type, so no backfill.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0051"
down_revision: str | None = "0050"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS future_states (
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
            CONSTRAINT ck_future_states_scope_matches_owner CHECK (
                (scope = 'organization' AND organization_id IS NOT NULL AND project_id IS NULL) OR
                (scope = 'project' AND project_id IS NOT NULL AND organization_id IS NULL)
            )
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_future_states_organization_id ON future_states (organization_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_future_states_project_id ON future_states (project_id)")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS future_state_versions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            future_state_id UUID NOT NULL REFERENCES future_states(id) ON DELETE CASCADE,
            version_number INTEGER NOT NULL,
            valid_from TIMESTAMPTZ NOT NULL,
            valid_to TIMESTAMPTZ,
            title VARCHAR(300) NOT NULL,
            current_state TEXT NOT NULL DEFAULT '',
            desired_state TEXT NOT NULL DEFAULT '',
            target_date DATE,
            outcomes TEXT NOT NULL DEFAULT '',
            success_measures TEXT NOT NULL DEFAULT '',
            constraints TEXT NOT NULL DEFAULT '',
            assumptions TEXT NOT NULL DEFAULT '',
            status VARCHAR(20) NOT NULL DEFAULT 'draft',
            change_note TEXT NOT NULL DEFAULT '',
            created_by UUID NOT NULL REFERENCES users(id),
            created_at TIMESTAMPTZ NOT NULL,
            UNIQUE (future_state_id, version_number)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_future_state_versions_current ON future_state_versions (future_state_id) "
        "WHERE valid_to IS NULL"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS future_state_comments (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            future_state_id UUID NOT NULL REFERENCES future_states(id) ON DELETE CASCADE,
            author_id UUID NOT NULL REFERENCES users(id),
            body TEXT NOT NULL,
            edited_at TIMESTAMPTZ
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS future_state_comment_files (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            comment_id UUID NOT NULL REFERENCES future_state_comments(id) ON DELETE CASCADE,
            file_id UUID NOT NULL REFERENCES file_assets(id) ON DELETE CASCADE,
            uploaded_by UUID NOT NULL REFERENCES users(id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_future_state_comment_files_comment_id ON future_state_comment_files (comment_id)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS future_state_files (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            future_state_id UUID NOT NULL REFERENCES future_states(id) ON DELETE CASCADE,
            file_id UUID NOT NULL REFERENCES file_assets(id) ON DELETE CASCADE,
            linked_by UUID NOT NULL REFERENCES users(id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (future_state_id, file_id)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS future_state_files")
    op.execute("DROP TABLE IF EXISTS future_state_comment_files")
    op.execute("DROP TABLE IF EXISTS future_state_comments")
    op.execute("DROP TABLE IF EXISTS future_state_versions")
    op.execute("DROP TABLE IF EXISTS future_states")
