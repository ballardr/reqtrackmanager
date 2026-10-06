"""Link-type direction (`flow`) on requirement link types

Revision ID: 0065
Revises: 0064
Create Date: 2026-10-06

Adds `requirement_link_type_definitions.flow` (`app.models.enums.LinkFlow`):
whether the target of a link of this type is upstream or downstream of its
source, so the artefact link graph can split neighbours into upstream /
downstream / related. Existing rows default to `none` (unclassified), which
changes nothing for them until an organisation admin sets a direction.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0065"
down_revision: str | None = "0064"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Adds the `flow` column, defaulting every existing type to `none`."""
    op.execute(
        "ALTER TABLE requirement_link_type_definitions "
        "ADD COLUMN IF NOT EXISTS flow VARCHAR(30) NOT NULL DEFAULT 'none'"
    )


def downgrade() -> None:
    """Drops the `flow` column."""
    op.execute("ALTER TABLE requirement_link_type_definitions DROP COLUMN IF EXISTS flow")
