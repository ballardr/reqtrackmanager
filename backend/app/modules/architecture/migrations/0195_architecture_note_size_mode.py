"""System Architecture note size mode

Revision ID: 0195
Revises: 0194
Create Date: 2026-11-16

Adds `size_mode` (`automatic` or `manual`) to `architecture_diagram_notes`. A note with no tone becomes `automatic` (its
box is invisible, so it is sized to its text); every other existing note stays `manual`, so a box a person sized does not change
on upgrade. The stored width and height are not touched.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0195"
down_revision: str | None = "0194"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE architecture_diagram_notes ADD COLUMN IF NOT EXISTS size_mode VARCHAR(16) NOT NULL DEFAULT 'manual'")
    op.execute("UPDATE architecture_diagram_notes SET size_mode = 'automatic' WHERE tone = 'none'")
    op.execute("ALTER TABLE architecture_diagram_notes DROP CONSTRAINT IF EXISTS ck_architecture_diagram_notes_size_mode")
    op.execute(
        "ALTER TABLE architecture_diagram_notes ADD CONSTRAINT ck_architecture_diagram_notes_size_mode "
        "CHECK (size_mode IN ('automatic', 'manual'))"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE architecture_diagram_notes DROP CONSTRAINT IF EXISTS ck_architecture_diagram_notes_size_mode")
    op.execute("ALTER TABLE architecture_diagram_notes DROP COLUMN IF EXISTS size_mode")
