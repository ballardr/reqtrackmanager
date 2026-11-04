"""Enhancement request merges

Revision ID: 0131
Revises: 0130
Create Date: 2026-11-04

Adds `enhancement_request_merges`: the recorded history that makes a merge of duplicate requests
reversible. A row is "active" while `unmerged_at` is null; at most one active row per duplicate.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0131"
down_revision: str | None = "0130"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS enhancement_request_merges (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            canonical_id UUID NOT NULL REFERENCES enhancement_requests(id) ON DELETE CASCADE,
            duplicate_id UUID NOT NULL REFERENCES enhancement_requests(id) ON DELETE CASCADE,
            prior_status VARCHAR(20) NOT NULL,
            merged_by UUID NOT NULL REFERENCES users(id),
            merged_at TIMESTAMPTZ NOT NULL,
            unmerged_by UUID REFERENCES users(id),
            unmerged_at TIMESTAMPTZ,
            CONSTRAINT ck_enhancement_request_merges_distinct CHECK (canonical_id <> duplicate_id)
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_enhancement_request_merges_active_duplicate "
        "ON enhancement_request_merges (duplicate_id) WHERE unmerged_at IS NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_enhancement_request_merges_canonical "
        "ON enhancement_request_merges (canonical_id) WHERE unmerged_at IS NULL"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS enhancement_request_merges")
