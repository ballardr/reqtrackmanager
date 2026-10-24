"""Pain Point types get an optional definition

Revision ID: 0104
Revises: 0103
Create Date: 2026-10-23

Adds `definition` to `pain_point_type_definitions` (the organisation's text) and `definition_override` to
`project_pain_point_types` (a project's own text for an organisation type, or a project-only type's
definition). Both are nullable, so existing rows keep no definition. Guarded: a database built from the
current models already has the columns.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0104"
down_revision: str | None = "0103"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE pain_point_type_definitions ADD COLUMN IF NOT EXISTS definition TEXT")
    op.execute("ALTER TABLE project_pain_point_types ADD COLUMN IF NOT EXISTS definition_override TEXT")


def downgrade() -> None:
    op.execute("ALTER TABLE project_pain_point_types DROP COLUMN IF EXISTS definition_override")
    op.execute("ALTER TABLE pain_point_type_definitions DROP COLUMN IF EXISTS definition")
