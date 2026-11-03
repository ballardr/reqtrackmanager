"""Shared autosaved layout drafts: report_layout_drafts

Revision ID: 0129
Revises: 0128
Create Date: 2026-11-03

Adds `report_layout_drafts`: at most one mutable working copy per report layout (unique `layout_id`, removed with the
layout), holding the tree the designer autosaves until a person publishes it as a numbered version. Guarded: a database
built from the current models already has it.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0129"
down_revision: str | None = "0128"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS report_layout_drafts (
            id UUID PRIMARY KEY,
            layout_id UUID NOT NULL UNIQUE REFERENCES report_layouts(id) ON DELETE CASCADE,
            tree JSONB NOT NULL,
            tree_hash VARCHAR(64) NOT NULL,
            base_version INTEGER NOT NULL,
            revision INTEGER NOT NULL DEFAULT 1,
            updated_by UUID REFERENCES users(id) ON DELETE SET NULL,
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS report_layout_drafts")
