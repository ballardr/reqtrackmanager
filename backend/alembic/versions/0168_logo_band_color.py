"""`logo_band_color_hex` on `server_settings` and `organizations`: the band drawn behind the logo.

Revision ID: 0168
Revises: 0167
Create Date: 2026-11-11

Null on every existing row (the band then follows the platform value, then the application top bar colour). Guarded so
a database built from the current models passes.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0168"
down_revision: str | None = "0167"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE server_settings ADD COLUMN IF NOT EXISTS logo_band_color_hex VARCHAR(7)")
    op.execute("ALTER TABLE organizations ADD COLUMN IF NOT EXISTS logo_band_color_hex VARCHAR(7)")


def downgrade() -> None:
    op.execute("ALTER TABLE organizations DROP COLUMN IF EXISTS logo_band_color_hex")
    op.execute("ALTER TABLE server_settings DROP COLUMN IF EXISTS logo_band_color_hex")
