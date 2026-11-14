"""Record comments: `record_comment_pins` and `record_comments`.

Revision ID: 0184
Revises: 0183
Create Date: 2026-11-14

Generic comments on records of any registered artefact type that opts in (`ModuleDefinition.record_comments`), keyed by
the artefact type string and the record id as tags and placements are. A pin places one thread on a record's drawing
(a free spot, a box or a line) and holds its resolved state; a comment with no pin is an ordinary comment on the record.
Nothing is backfilled: no record has comments in these tables yet. Guarded so a database built from the current models
passes.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0184"
down_revision: str | None = "0183"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS record_comment_pins (
            id UUID PRIMARY KEY,
            project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
            organization_id UUID REFERENCES organizations(id) ON DELETE CASCADE,
            artefact_type VARCHAR(40) NOT NULL,
            record_id UUID NOT NULL,
            anchor_kind VARCHAR(8) NOT NULL DEFAULT 'none',
            anchor_key VARCHAR(80),
            x DOUBLE PRECISION NOT NULL DEFAULT 0,
            y DOUBLE PRECISION NOT NULL DEFAULT 0,
            resolved_at TIMESTAMPTZ,
            resolved_by UUID REFERENCES users(id) ON DELETE SET NULL,
            created_by UUID REFERENCES users(id) ON DELETE SET NULL,
            created_at TIMESTAMPTZ NOT NULL,
            CONSTRAINT ck_record_comment_pins_one_owner CHECK ((project_id IS NOT NULL) <> (organization_id IS NOT NULL)),
            CONSTRAINT ck_record_comment_pins_anchor_kind CHECK (anchor_kind IN ('none', 'node', 'edge')),
            CONSTRAINT ck_record_comment_pins_anchor_key CHECK ((anchor_kind = 'none') = (anchor_key IS NULL))
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_record_comment_pins_project_id ON record_comment_pins (project_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_record_comment_pins_organization_id ON record_comment_pins (organization_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_record_comment_pins_record ON record_comment_pins (artefact_type, record_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_record_comment_pins_anchor ON record_comment_pins (anchor_kind, anchor_key)")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS record_comments (
            id UUID PRIMARY KEY,
            project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
            organization_id UUID REFERENCES organizations(id) ON DELETE CASCADE,
            artefact_type VARCHAR(40) NOT NULL,
            record_id UUID NOT NULL,
            pin_id UUID REFERENCES record_comment_pins(id) ON DELETE CASCADE,
            author_id UUID REFERENCES users(id) ON DELETE SET NULL,
            body TEXT NOT NULL,
            edited_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            CONSTRAINT ck_record_comments_one_owner CHECK ((project_id IS NOT NULL) <> (organization_id IS NOT NULL))
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_record_comments_project_id ON record_comments (project_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_record_comments_organization_id ON record_comments (organization_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_record_comments_record ON record_comments (artefact_type, record_id, created_at)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_record_comments_pin ON record_comments (pin_id, created_at)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS record_comments")
    op.execute("DROP TABLE IF EXISTS record_comment_pins")
