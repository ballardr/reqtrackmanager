"""Open Question data model (Module 1 Phase 5)

Revision ID: 0054
Revises: 0053
Create Date: 2026-09-28

Adds the four tables backing Context & Strategy's Phase 5 data model
(docs/plans/module-01-context-and-strategy-plan.md Phase 5 — Open
Questions), back to migration 0052's Pain Point shape (no identity+version
split — see `models.py`'s own docstring for the full reasoning), not
migration 0053's Guiding Principle shape:

- `open_questions` (the artefact itself — project-scoped only, no version
  table, no `type` field; `question`/`context`/`evidence` are `Text`).
- `open_question_comments` / `open_question_comment_files` /
  `open_question_files` — this module's own module-local comment-thread and
  attachment tables, mirroring `pain_point_comments`/`pain_point_comment_
  files`/`pain_point_files`.

No backfill needed — this is a brand-new artefact type with no pre-existing
rows anywhere.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0054"
down_revision: str | None = "0053"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS open_questions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            question TEXT NOT NULL,
            context TEXT NOT NULL DEFAULT '',
            evidence TEXT NOT NULL DEFAULT '',
            priority VARCHAR(20) NOT NULL DEFAULT 'medium',
            status VARCHAR(20) NOT NULL DEFAULT 'open',
            owner_id UUID REFERENCES users(id),
            due_date DATE,
            creator_id UUID NOT NULL REFERENCES users(id),
            is_archived BOOLEAN NOT NULL DEFAULT false,
            archived_at TIMESTAMPTZ,
            archived_by UUID REFERENCES users(id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS open_question_comments (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            open_question_id UUID NOT NULL REFERENCES open_questions(id) ON DELETE CASCADE,
            author_id UUID NOT NULL REFERENCES users(id),
            body TEXT NOT NULL,
            edited_at TIMESTAMPTZ
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS open_question_comment_files (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            comment_id UUID NOT NULL REFERENCES open_question_comments(id) ON DELETE CASCADE,
            file_id UUID NOT NULL REFERENCES file_assets(id) ON DELETE CASCADE,
            uploaded_by UUID NOT NULL REFERENCES users(id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_open_question_comment_files_comment_id ON open_question_comment_files (comment_id)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS open_question_files (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            open_question_id UUID NOT NULL REFERENCES open_questions(id) ON DELETE CASCADE,
            file_id UUID NOT NULL REFERENCES file_assets(id) ON DELETE CASCADE,
            linked_by UUID NOT NULL REFERENCES users(id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (open_question_id, file_id)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS open_question_files")
    op.execute("DROP TABLE IF EXISTS open_question_comment_files")
    op.execute("DROP TABLE IF EXISTS open_question_comments")
    op.execute("DROP TABLE IF EXISTS open_questions")
