"""System Architecture note leaders as drawn lines

Revision ID: 0190
Revises: 0189
Create Date: 2026-11-16

Moves a note's leader out of `architecture_diagram_notes` into its own table, `architecture_note_leaders`, so a note can
have several and each is a drawn line: a start attach point, an end (a box, a line or a free point), waypoints, a smooth
curve and a start and an end style (none, arrow or dot). Every existing leader becomes one row meaning the same: its kind,
target and point carry over, and `leader_arrow` becomes an end style of arrow (or none) with a start style of none. A note
whose leader had lost its target already read as having none and gets no row. The leader columns are then removed from the
note. Deleting a leader's target element or connection deletes the leader row (the note stays).

The downgrade writes each note's first leader back into the note columns and drops the table (a second leader and the
waypoints, start point and styles have nowhere to go).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0190"
down_revision: str | None = "0189"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS architecture_note_leaders (
            id UUID PRIMARY KEY,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            note_id UUID NOT NULL REFERENCES architecture_diagram_notes(id) ON DELETE CASCADE,
            sort_order INTEGER NOT NULL DEFAULT 0,
            kind VARCHAR(16) NOT NULL,
            element_id UUID REFERENCES architecture_elements(id) ON DELETE CASCADE,
            connection_id UUID REFERENCES architecture_connections(id) ON DELETE CASCADE,
            x DOUBLE PRECISION,
            y DOUBLE PRECISION,
            start_point VARCHAR(16),
            points JSONB NOT NULL DEFAULT '[]'::jsonb,
            smooth BOOLEAN NOT NULL DEFAULT false,
            start_style VARCHAR(8) NOT NULL DEFAULT 'none',
            end_style VARCHAR(8) NOT NULL DEFAULT 'arrow',
            CONSTRAINT ck_architecture_note_leaders_kind CHECK (kind IN ('element', 'connection', 'point')),
            CONSTRAINT ck_architecture_note_leaders_target CHECK (
                (kind = 'element') = (element_id IS NOT NULL)
                AND (kind = 'connection') = (connection_id IS NOT NULL)
                AND (kind = 'point') = (x IS NOT NULL AND y IS NOT NULL)
                AND (kind = 'point' OR (x IS NULL AND y IS NULL))
            ),
            CONSTRAINT ck_architecture_note_leaders_style CHECK (
                start_style IN ('none', 'arrow', 'dot') AND end_style IN ('none', 'arrow', 'dot')
            )
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_architecture_note_leaders_note_id ON architecture_note_leaders (note_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_architecture_note_leaders_element_id ON architecture_note_leaders (element_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_architecture_note_leaders_connection_id ON architecture_note_leaders (connection_id)")
    # Only when the old columns are still there (a database built from the models has none to move).
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'architecture_diagram_notes' AND column_name = 'leader_kind'
            ) THEN
                INSERT INTO architecture_note_leaders (
                    id, note_id, sort_order, kind, element_id, connection_id, x, y, end_style, created_at, updated_at
                )
                SELECT gen_random_uuid(), id, 0, leader_kind, leader_element_id, leader_connection_id, leader_x, leader_y,
                       CASE WHEN leader_arrow THEN 'arrow' ELSE 'none' END, created_at, updated_at
                FROM architecture_diagram_notes
                WHERE (leader_kind = 'element' AND leader_element_id IS NOT NULL)
                   OR (leader_kind = 'connection' AND leader_connection_id IS NOT NULL)
                   OR (leader_kind = 'point' AND leader_x IS NOT NULL AND leader_y IS NOT NULL);
            END IF;
        END $$
        """
    )
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
            DROP COLUMN IF EXISTS leader_kind
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE architecture_diagram_notes
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
        UPDATE architecture_diagram_notes n SET
            leader_kind = l.kind, leader_element_id = l.element_id, leader_connection_id = l.connection_id,
            leader_x = l.x, leader_y = l.y, leader_arrow = (l.end_style = 'arrow')
        FROM (
            SELECT DISTINCT ON (note_id) * FROM architecture_note_leaders ORDER BY note_id, sort_order, id
        ) l
        WHERE l.note_id = n.id
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
    op.execute("DROP TABLE IF EXISTS architecture_note_leaders")
