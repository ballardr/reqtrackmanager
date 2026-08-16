"""Organisation label override

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-16

- `server_settings.org_label_singular` / `org_label_plural`: nullable
  deployment-wide override of the word "organisation"/"Organisations" shown
  throughout the UI. `NULL` for either falls back to the built-in English
  word.

`IF NOT EXISTS`, same reason 0002-0005 use it: a brand-new database's
`create_all()` already creates these columns against the current model
class, so a plain `ADD COLUMN` would fail there with "already exists"; an
already-migrated database from before this revision is genuinely missing
them.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE server_settings ADD COLUMN IF NOT EXISTS org_label_singular VARCHAR(50)")
    op.execute("ALTER TABLE server_settings ADD COLUMN IF NOT EXISTS org_label_plural VARCHAR(50)")


def downgrade() -> None:
    op.execute("ALTER TABLE server_settings DROP COLUMN IF EXISTS org_label_singular")
    op.execute("ALTER TABLE server_settings DROP COLUMN IF EXISTS org_label_plural")
