"""Enhancement request informed requesters

Revision ID: 0136
Revises: 0135
Create Date: 2026-11-05

Adds `enhancement_request_informed`: one row per requester (a Stakeholder or Persona) recorded as told the outcome of
a delivered or declined request, the close-the-loop list's source. The party has no foreign key (it belongs to
another module); it is matched against the request's requesters on read.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0136"
down_revision: str | None = "0135"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS enhancement_request_informed (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            request_id UUID NOT NULL REFERENCES enhancement_requests(id) ON DELETE CASCADE,
            party_type VARCHAR(64) NOT NULL,
            party_id UUID NOT NULL,
            informed_by UUID NOT NULL REFERENCES users(id),
            informed_at TIMESTAMPTZ NOT NULL,
            note TEXT NOT NULL DEFAULT '',
            CONSTRAINT uq_enhancement_request_informed_party UNIQUE (request_id, party_type, party_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_enhancement_request_informed_request_id "
        "ON enhancement_request_informed (request_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS enhancement_request_informed")
