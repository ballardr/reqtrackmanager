"""Server report fonts: server_report_fonts

Revision ID: 0127
Revises: 0126
Create Date: 2026-11-02

Adds `server_report_fonts`: the server administrator's per-family settings for the extra report fonts found in the
mounted font directory (name for Word and OpenDocument, generic fallback, hidden from authors). Guarded: a database built
from the current models already has it.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0127"
down_revision: str | None = "0126"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS server_report_fonts (
            id UUID PRIMARY KEY,
            font_key VARCHAR(80) NOT NULL UNIQUE,
            word_name VARCHAR(100),
            generic VARCHAR(20) NOT NULL DEFAULT 'sans-serif',
            enabled BOOLEAN NOT NULL DEFAULT true,
            updated_by UUID REFERENCES users(id),
            created_at TIMESTAMP WITH TIME ZONE NOT NULL,
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS server_report_fonts")
