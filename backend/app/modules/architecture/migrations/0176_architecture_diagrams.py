"""System Architecture diagrams: diagrams, placements, notes, view toggles and their manual members

Revision ID: 0176
Revises: 0175
Create Date: 2026-11-12

Adds `architecture_diagrams` (a saved view of a project's model, with its own code and version),
`architecture_diagram_placements` (one per element per diagram), `architecture_diagram_notes` (plain text),
`architecture_diagram_toggles` (a named switch with a rule) and `architecture_diagram_toggle_members` (the elements
and connections a toggle names by hand; exactly one of the two ids).

A diagram holds no truth of its own: deleting an element removes its placements and toggle memberships, and an
element used as a diagram's scope falls back to the system context (`SET NULL`). Nothing is seeded.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0176"
down_revision: str | None = "0175"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS architecture_diagrams (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            unique_code VARCHAR(64) NOT NULL,
            name VARCHAR(200) NOT NULL,
            purpose TEXT NOT NULL DEFAULT '',
            scope_element_id UUID REFERENCES architecture_elements(id) ON DELETE SET NULL,
            connection_detail BOOLEAN NOT NULL DEFAULT false,
            status VARCHAR(20) NOT NULL DEFAULT 'draft',
            version INTEGER NOT NULL DEFAULT 1,
            creator_id UUID NOT NULL REFERENCES users(id),
            is_archived BOOLEAN NOT NULL DEFAULT false,
            archived_at TIMESTAMPTZ,
            archived_by UUID REFERENCES users(id),
            CONSTRAINT uq_architecture_diagrams_project_unique_code UNIQUE (project_id, unique_code)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_architecture_diagrams_project_id ON architecture_diagrams (project_id)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_architecture_diagrams_scope_element_id ON architecture_diagrams (scope_element_id)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS architecture_diagram_placements (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            diagram_id UUID NOT NULL REFERENCES architecture_diagrams(id) ON DELETE CASCADE,
            element_id UUID NOT NULL REFERENCES architecture_elements(id) ON DELETE CASCADE,
            x DOUBLE PRECISION NOT NULL DEFAULT 0,
            y DOUBLE PRECISION NOT NULL DEFAULT 0,
            width DOUBLE PRECISION NOT NULL DEFAULT 160,
            height DOUBLE PRECISION NOT NULL DEFAULT 80,
            collapsed BOOLEAN NOT NULL DEFAULT false,
            CONSTRAINT uq_architecture_diagram_placements UNIQUE (diagram_id, element_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_architecture_diagram_placements_diagram_id ON architecture_diagram_placements (diagram_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_architecture_diagram_placements_element_id ON architecture_diagram_placements (element_id)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS architecture_diagram_notes (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            diagram_id UUID NOT NULL REFERENCES architecture_diagrams(id) ON DELETE CASCADE,
            text TEXT NOT NULL DEFAULT '',
            x DOUBLE PRECISION NOT NULL DEFAULT 0,
            y DOUBLE PRECISION NOT NULL DEFAULT 0,
            width DOUBLE PRECISION NOT NULL DEFAULT 160,
            height DOUBLE PRECISION NOT NULL DEFAULT 60,
            sort_order INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_architecture_diagram_notes_diagram_id ON architecture_diagram_notes (diagram_id)")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS architecture_diagram_toggles (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            diagram_id UUID NOT NULL REFERENCES architecture_diagrams(id) ON DELETE CASCADE,
            name VARCHAR(100) NOT NULL,
            default_on BOOLEAN NOT NULL DEFAULT true,
            rule JSONB NOT NULL DEFAULT '{}'::jsonb,
            sort_order INTEGER NOT NULL DEFAULT 0,
            CONSTRAINT uq_architecture_diagram_toggles_name UNIQUE (diagram_id, name)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_architecture_diagram_toggles_diagram_id ON architecture_diagram_toggles (diagram_id)")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS architecture_diagram_toggle_members (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            toggle_id UUID NOT NULL REFERENCES architecture_diagram_toggles(id) ON DELETE CASCADE,
            element_id UUID REFERENCES architecture_elements(id) ON DELETE CASCADE,
            connection_id UUID REFERENCES architecture_connections(id) ON DELETE CASCADE,
            CONSTRAINT ck_architecture_diagram_toggle_members_one CHECK ((element_id IS NULL) <> (connection_id IS NULL)),
            CONSTRAINT uq_architecture_diagram_toggle_members_element UNIQUE (toggle_id, element_id),
            CONSTRAINT uq_architecture_diagram_toggle_members_connection UNIQUE (toggle_id, connection_id)
        )
        """
    )
    for column in ("toggle_id", "element_id", "connection_id"):
        op.execute(
            f"CREATE INDEX IF NOT EXISTS ix_architecture_diagram_toggle_members_{column} "
            f"ON architecture_diagram_toggle_members ({column})"
        )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS architecture_diagram_toggle_members")
    op.execute("DROP TABLE IF EXISTS architecture_diagram_toggles")
    op.execute("DROP TABLE IF EXISTS architecture_diagram_notes")
    op.execute("DROP TABLE IF EXISTS architecture_diagram_placements")
    op.execute("DROP TABLE IF EXISTS architecture_diagrams")
