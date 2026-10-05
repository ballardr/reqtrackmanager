"""Pain Point data model (Module 1 Phase 3)

Revision ID: 0052
Revises: 0051
Create Date: 2026-09-28

Adds the six tables backing Context & Strategy's Phase 3 data model
(docs/plans/module-01-context-and-strategy-plan.md Phase 3 — Pain Points),
a structurally different shape from migrations 0048/0051's identity+version
pairs (see `models.py`'s own docstring for the full reasoning):

- `pain_point_type_definitions` (org-scoped base type vocabulary, Phase 0
  Q3's two-tier design — same shape as `requirement_link_type_definitions`).
- `project_pain_point_types` (project-scoped: either a local override of
  one org type, via `org_type_id`, or a fully project-local type when
  `org_type_id` is NULL — enforced by a CHECK constraint that a NULL
  `org_type_id` row must carry its own `name_override`).
- `pain_points` (the artefact itself — project-scoped only, no version
  table; `pain_point_type_id` is a NOT NULL FK to `project_pain_point_types`,
  never directly to `pain_point_type_definitions`).
- `pain_point_comments` / `pain_point_comment_files` / `pain_point_files`
  — this module's own module-local comment-thread and attachment tables,
  mirroring `strategy_comments`/`strategy_comment_files`/`strategy_files`.

No backfill needed — this is a brand-new artefact type with no
pre-existing rows anywhere. `pain_point_type_definitions`' Market/User/
Operator defaults (source overview §6.2) are seeded per-organisation at
organisation-creation time (`app.modules.context_strategy.service.
seed_default_pain_point_types`, via `ModuleDefinition.on_org_created`),
not backfilled here for already-existing organisations — this module is
`default_enabled=False`, so an org only sees Pain Points at all once it
explicitly enables the module, at which point Phase 7's own frontend
onboarding (not yet built) is the natural point to offer seeding existing
orgs' defaults, matching how Strategy/Future State (Phases 1-2) needed no
backfill of their own either.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0052"
down_revision: str | None = "0051"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS pain_point_type_definitions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            name VARCHAR(100) NOT NULL,
            sort_order INTEGER NOT NULL DEFAULT 0,
            is_active BOOLEAN NOT NULL DEFAULT true,
            CONSTRAINT uq_pain_point_type_definitions_org_name UNIQUE (organization_id, name)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS project_pain_point_types (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            org_type_id UUID REFERENCES pain_point_type_definitions(id) ON DELETE SET NULL,
            name_override VARCHAR(100),
            display_order_override INTEGER,
            is_enabled BOOLEAN NOT NULL DEFAULT true,
            CONSTRAINT uq_project_pain_point_types_project_org_type UNIQUE (project_id, org_type_id),
            CONSTRAINT ck_project_pain_point_types_local_has_name CHECK (
                org_type_id IS NOT NULL OR name_override IS NOT NULL
            )
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS pain_points (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            pain_point_type_id UUID NOT NULL REFERENCES project_pain_point_types(id),
            title VARCHAR(300) NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            source TEXT NOT NULL DEFAULT '',
            impact TEXT NOT NULL DEFAULT '',
            evidence TEXT NOT NULL DEFAULT '',
            priority VARCHAR(20) NOT NULL DEFAULT 'medium',
            status VARCHAR(20) NOT NULL DEFAULT 'submitted',
            owner_id UUID REFERENCES users(id),
            date_identified DATE NOT NULL,
            creator_id UUID NOT NULL REFERENCES users(id),
            is_archived BOOLEAN NOT NULL DEFAULT false,
            archived_at TIMESTAMPTZ,
            archived_by UUID REFERENCES users(id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS pain_point_comments (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            pain_point_id UUID NOT NULL REFERENCES pain_points(id) ON DELETE CASCADE,
            author_id UUID NOT NULL REFERENCES users(id),
            body TEXT NOT NULL,
            edited_at TIMESTAMPTZ
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS pain_point_comment_files (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            comment_id UUID NOT NULL REFERENCES pain_point_comments(id) ON DELETE CASCADE,
            file_id UUID NOT NULL REFERENCES file_assets(id) ON DELETE CASCADE,
            uploaded_by UUID NOT NULL REFERENCES users(id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_pain_point_comment_files_comment_id ON pain_point_comment_files (comment_id)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS pain_point_files (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            pain_point_id UUID NOT NULL REFERENCES pain_points(id) ON DELETE CASCADE,
            file_id UUID NOT NULL REFERENCES file_assets(id) ON DELETE CASCADE,
            linked_by UUID NOT NULL REFERENCES users(id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (pain_point_id, file_id)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS pain_point_files")
    op.execute("DROP TABLE IF EXISTS pain_point_comment_files")
    op.execute("DROP TABLE IF EXISTS pain_point_comments")
    op.execute("DROP TABLE IF EXISTS pain_points")
    op.execute("DROP TABLE IF EXISTS project_pain_point_types")
    op.execute("DROP TABLE IF EXISTS pain_point_type_definitions")
