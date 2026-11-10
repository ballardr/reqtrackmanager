"""Footer prefix and company identifier

Revision ID: 0160
Revises: 0159
Create Date: 2026-11-10

`server_settings.footer_prefix`, `company_id_label` and `company_id`: the text shown before the platform company name in
the page and email footers, and the company's registration identifier (for example an ABN). All nullable; existing
deployments show neither until a server administrator sets them. Guarded so a database built from the current models
passes.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0160"
down_revision: str | None = "0159"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE server_settings ADD COLUMN IF NOT EXISTS footer_prefix VARCHAR(50)")
    op.execute("ALTER TABLE server_settings ADD COLUMN IF NOT EXISTS company_id_label VARCHAR(50)")
    op.execute("ALTER TABLE server_settings ADD COLUMN IF NOT EXISTS company_id VARCHAR(100)")


def downgrade() -> None:
    op.execute("ALTER TABLE server_settings DROP COLUMN IF EXISTS company_id")
    op.execute("ALTER TABLE server_settings DROP COLUMN IF EXISTS company_id_label")
    op.execute("ALTER TABLE server_settings DROP COLUMN IF EXISTS footer_prefix")
