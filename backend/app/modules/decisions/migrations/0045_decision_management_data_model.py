"""Decision Management data model (Module 4 Phase 1)

Revision ID: 0045
Revises: 0044
Create Date: 2026-09-21

Adds the six tables backing Decision Management's data model
(docs/plans/module-04-decision-management-plan.md Phase 1):

- `decision_type_definitions` (project-scoped, mirrors
  `action_type_definitions` exactly).
- `decision_template_definitions` (org-scoped; per-field guidance text,
  not FK'd to a decision type — see `app.modules.decisions.models.
  DecisionTemplateDefinition`'s own docstring for why).
- `decisions` — the record itself.
- `decision_comments` / `decision_comment_files` / `decision_files` — this
  module's own module-local comment-thread and attachment tables.

Also backfills `decision_type_definitions` with the 5 defaults
(`app.modules.decisions.service.DEFAULT_DECISION_TYPES`) for every project
that already exists — going forward, every new project gets these seeded
at creation time by `app.modules.decisions.module._seed_new_project`
(`on_project_created`). Mirrors migration 0032's identical backfill
pattern for compliance action types: an `INSERT ... SELECT ... WHERE NOT
EXISTS` per project, safe to run unconditionally.

No `decision_template_definitions` backfill — template seeding is opt-in
per organisation at creation time (Phase 0 addendum Q1), so a pre-existing
organisation simply starts with none; an org admin can create custom ones
by hand once Phase 4's API ships.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0045"
down_revision: str | None = "0044"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DEFAULT_DECISION_TYPES = ["Architecture", "Design", "Engineering", "Strategy", "Operational"]


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS decision_type_definitions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            name VARCHAR(100) NOT NULL,
            sort_order INTEGER NOT NULL DEFAULT 0,
            UNIQUE (project_id, name)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS decision_template_definitions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            name VARCHAR(200) NOT NULL,
            description TEXT,
            context_prompt TEXT,
            options_considered_prompt TEXT,
            chosen_option_prompt TEXT,
            rationale_prompt TEXT,
            consequences_prompt TEXT,
            assumptions_prompt TEXT,
            constraints_prompt TEXT,
            sort_order INTEGER NOT NULL DEFAULT 0,
            UNIQUE (organization_id, name)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS decisions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            unique_code VARCHAR(64) NOT NULL,
            title VARCHAR(300) NOT NULL,
            decision_statement TEXT NOT NULL,
            decision_type_id UUID NOT NULL REFERENCES decision_type_definitions(id),
            status VARCHAR(20) NOT NULL DEFAULT 'draft',
            decision_date DATE,
            decision_maker_id UUID REFERENCES users(id),
            owner_id UUID NOT NULL REFERENCES users(id),
            context TEXT,
            options_considered TEXT,
            chosen_option TEXT,
            rationale TEXT,
            consequences TEXT,
            assumptions TEXT,
            constraints TEXT,
            creator_id UUID NOT NULL REFERENCES users(id),
            is_archived BOOLEAN NOT NULL DEFAULT false,
            archived_at TIMESTAMPTZ,
            archived_by UUID REFERENCES users(id),
            UNIQUE (project_id, unique_code)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_decisions_unique_code ON decisions (unique_code)")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS decision_comments (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            decision_id UUID NOT NULL REFERENCES decisions(id) ON DELETE CASCADE,
            author_id UUID NOT NULL REFERENCES users(id),
            body TEXT NOT NULL,
            edited_at TIMESTAMPTZ
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS decision_comment_files (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            comment_id UUID NOT NULL REFERENCES decision_comments(id) ON DELETE CASCADE,
            file_id UUID NOT NULL REFERENCES file_assets(id) ON DELETE CASCADE,
            uploaded_by UUID NOT NULL REFERENCES users(id)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_decision_comment_files_comment_id ON decision_comment_files (comment_id)")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS decision_files (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            decision_id UUID NOT NULL REFERENCES decisions(id) ON DELETE CASCADE,
            file_id UUID NOT NULL REFERENCES file_assets(id) ON DELETE CASCADE,
            linked_by UUID NOT NULL REFERENCES users(id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (decision_id, file_id)
        )
        """
    )

    for sort_order, name in enumerate(_DEFAULT_DECISION_TYPES):
        op.execute(
            f"""
            INSERT INTO decision_type_definitions (id, created_at, updated_at, project_id, name, sort_order)
            SELECT gen_random_uuid(), now(), now(), p.id, '{name}', {sort_order}
            FROM projects p
            WHERE NOT EXISTS (
                SELECT 1 FROM decision_type_definitions dtd
                WHERE dtd.project_id = p.id AND dtd.name = '{name}'
            )
            """
        )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS decision_files")
    op.execute("DROP TABLE IF EXISTS decision_comment_files")
    op.execute("DROP TABLE IF EXISTS decision_comments")
    op.execute("DROP TABLE IF EXISTS decisions")
    op.execute("DROP TABLE IF EXISTS decision_template_definitions")
    op.execute("DROP TABLE IF EXISTS decision_type_definitions")
