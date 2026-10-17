"""Engagements and research extras

Revision ID: 0087
Revises: 0086
Create Date: 2026-10-13

Adds the project-scoped Engagement contact log: `engagements` with module-local
comment/attachment tables, plus the research extras' `engagement_prompts`,
`engagement_anonymous_participants` and `research_findings`. Participants,
personas covered, the audience group and the Pain Points / Needs / Open
Questions an engagement raised or answered are `artefact_links` rows, so need no
table of their own. Every child table cascades from `engagements`, so deleting
an engagement removes all of its data. Nothing is backfilled.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0087"
down_revision: str | None = "0086"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS engagements (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            creator_id UUID NOT NULL REFERENCES users(id),
            title VARCHAR(300) NOT NULL,
            channel VARCHAR(30) NOT NULL,
            engagement_date DATE NOT NULL,
            facilitator_type VARCHAR(20),
            facilitator_id UUID,
            purpose TEXT NOT NULL DEFAULT '',
            summary TEXT NOT NULL DEFAULT '',
            notes TEXT NOT NULL DEFAULT '',
            consent_recorded BOOLEAN NOT NULL DEFAULT false,
            retain_until DATE,
            CONSTRAINT ck_facilitator_principal CHECK (
                (facilitator_type IS NULL OR facilitator_type IN ('user', 'org_group', 'project_group'))
                AND (facilitator_type IS NULL) = (facilitator_id IS NULL)
            )
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_engagements_project_id ON engagements (project_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_engagements_engagement_date ON engagements (engagement_date)")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS engagement_comments (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            engagement_id UUID NOT NULL REFERENCES engagements(id) ON DELETE CASCADE,
            author_id UUID NOT NULL REFERENCES users(id),
            body TEXT NOT NULL,
            edited_at TIMESTAMPTZ
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS engagement_comment_files (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            comment_id UUID NOT NULL REFERENCES engagement_comments(id) ON DELETE CASCADE,
            file_id UUID NOT NULL REFERENCES file_assets(id) ON DELETE CASCADE,
            uploaded_by UUID NOT NULL REFERENCES users(id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_engagement_comment_files_comment_id ON engagement_comment_files (comment_id)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS engagement_files (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            engagement_id UUID NOT NULL REFERENCES engagements(id) ON DELETE CASCADE,
            file_id UUID NOT NULL REFERENCES file_assets(id) ON DELETE CASCADE,
            linked_by UUID NOT NULL REFERENCES users(id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (engagement_id, file_id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS engagement_prompts (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            engagement_id UUID NOT NULL REFERENCES engagements(id) ON DELETE CASCADE,
            sort_order INTEGER NOT NULL DEFAULT 0,
            prompt TEXT NOT NULL,
            response_notes TEXT NOT NULL DEFAULT ''
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_engagement_prompts_engagement_id ON engagement_prompts (engagement_id)")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS engagement_anonymous_participants (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            engagement_id UUID NOT NULL REFERENCES engagements(id) ON DELETE CASCADE,
            label VARCHAR(200) NOT NULL,
            persona_id UUID REFERENCES personas(id) ON DELETE SET NULL
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_engagement_anonymous_participants_engagement_id "
        "ON engagement_anonymous_participants (engagement_id)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS research_findings (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            engagement_id UUID NOT NULL REFERENCES engagements(id) ON DELETE CASCADE,
            creator_id UUID NOT NULL REFERENCES users(id),
            title VARCHAR(300) NOT NULL,
            description TEXT NOT NULL DEFAULT ''
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_research_findings_project_id ON research_findings (project_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_research_findings_engagement_id ON research_findings (engagement_id)")


def downgrade() -> None:
    for table in (
        "research_findings", "engagement_anonymous_participants", "engagement_prompts", "engagement_files",
        "engagement_comment_files", "engagement_comments", "engagements",
    ):
        op.execute(f"DROP TABLE IF EXISTS {table}")
