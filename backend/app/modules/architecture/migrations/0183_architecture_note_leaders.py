"""System Architecture annotation notes with leaders

Revision ID: 0183
Revises: 0182
Create Date: 2026-11-14

Adds the annotation columns to `architecture_diagram_notes`: a `tone`, and an optional leader line to an element's box, a
connection's line or a free point (`leader_kind`, `leader_element_id`, `leader_connection_id`, `leader_x`, `leader_y`,
`leader_arrow`). Existing notes become neutral notes with no leader, so nothing changes on screen. Deleting the target
element or connection empties its column (the note stays and its leader is read as none).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0183"
down_revision: str | None = "0182"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE architecture_diagram_notes
            ADD COLUMN IF NOT EXISTS tone VARCHAR(16) NOT NULL DEFAULT 'neutral',
            ADD COLUMN IF NOT EXISTS leader_kind VARCHAR(16) NOT NULL DEFAULT 'none',
            ADD COLUMN IF NOT EXISTS leader_element_id UUID REFERENCES architecture_elements(id) ON DELETE SET NULL,
            ADD COLUMN IF NOT EXISTS leader_connection_id UUID REFERENCES architecture_connections(id) ON DELETE SET NULL,
            ADD COLUMN IF NOT EXISTS leader_x DOUBLE PRECISION,
            ADD COLUMN IF NOT EXISTS leader_y DOUBLE PRECISION,
            ADD COLUMN IF NOT EXISTS leader_arrow BOOLEAN NOT NULL DEFAULT true
        """
    )
    op.execute(
        """
        ALTER TABLE architecture_diagram_notes
            DROP CONSTRAINT IF EXISTS ck_architecture_diagram_notes_leader_target,
            DROP CONSTRAINT IF EXISTS ck_architecture_diagram_notes_leader_kind
        """
    )
    op.execute(
        """
        ALTER TABLE architecture_diagram_notes
            ADD CONSTRAINT ck_architecture_diagram_notes_leader_kind
                CHECK (leader_kind IN ('none', 'element', 'connection', 'point')),
            ADD CONSTRAINT ck_architecture_diagram_notes_leader_target
                CHECK (
                    (leader_element_id IS NULL OR leader_kind = 'element')
                    AND (leader_connection_id IS NULL OR leader_kind = 'connection')
                    AND ((leader_x IS NULL AND leader_y IS NULL) OR leader_kind = 'point')
                    AND (leader_kind <> 'point' OR (leader_x IS NOT NULL AND leader_y IS NOT NULL))
                )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_architecture_diagram_notes_leader_element_id ON architecture_diagram_notes (leader_element_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_architecture_diagram_notes_leader_connection_id ON architecture_diagram_notes (leader_connection_id)")


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE architecture_diagram_notes
            DROP CONSTRAINT IF EXISTS ck_architecture_diagram_notes_leader_target,
            DROP CONSTRAINT IF EXISTS ck_architecture_diagram_notes_leader_kind,
            DROP COLUMN IF EXISTS leader_arrow,
            DROP COLUMN IF EXISTS leader_y,
            DROP COLUMN IF EXISTS leader_x,
            DROP COLUMN IF EXISTS leader_connection_id,
            DROP COLUMN IF EXISTS leader_element_id,
            DROP COLUMN IF EXISTS leader_kind,
            DROP COLUMN IF EXISTS tone
        """
    )
