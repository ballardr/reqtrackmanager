"""System Architecture element display note

Revision ID: 0182
Revises: 0181
Create Date: 2026-11-14

Adds `display_note` to `architecture_elements`: a short plain-text line drawn inside the element's box on every diagram
that places it, apart from the long `description`. Existing elements get an empty note, so nothing changes on screen.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0182"
down_revision: str | None = "0181"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE architecture_elements ADD COLUMN IF NOT EXISTS display_note VARCHAR(500) NOT NULL DEFAULT ''")


def downgrade() -> None:
    op.execute("ALTER TABLE architecture_elements DROP COLUMN IF EXISTS display_note")
