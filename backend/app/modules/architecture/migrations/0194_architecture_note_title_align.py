"""System Architecture note title and alignment

Revision ID: 0194
Revises: 0193
Create Date: 2026-11-16

Adds `title` (at most 120 characters, empty for none) and `text_align` (`left`, `center` or `right`) to
`architecture_diagram_notes`. Existing notes get no title and `left`, so no stored diagram changes on upgrade.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0194"
down_revision: str | None = "0193"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE architecture_diagram_notes ADD COLUMN IF NOT EXISTS title VARCHAR(120) NOT NULL DEFAULT ''")
    op.execute("ALTER TABLE architecture_diagram_notes ADD COLUMN IF NOT EXISTS text_align VARCHAR(16) NOT NULL DEFAULT 'left'")
    op.execute("ALTER TABLE architecture_diagram_notes DROP CONSTRAINT IF EXISTS ck_architecture_diagram_notes_text_align")
    op.execute(
        "ALTER TABLE architecture_diagram_notes ADD CONSTRAINT ck_architecture_diagram_notes_text_align "
        "CHECK (text_align IN ('left', 'center', 'right'))"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE architecture_diagram_notes DROP CONSTRAINT IF EXISTS ck_architecture_diagram_notes_text_align")
    op.execute("ALTER TABLE architecture_diagram_notes DROP COLUMN IF EXISTS text_align")
    op.execute("ALTER TABLE architecture_diagram_notes DROP COLUMN IF EXISTS title")
