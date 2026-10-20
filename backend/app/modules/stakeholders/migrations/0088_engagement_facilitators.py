"""Engagements can have several facilitators

Revision ID: 0088
Revises: 0087
Create Date: 2026-10-13

An engagement's single `facilitator_type` / `facilitator_id` pair becomes a list: one
`engagement_facilitators` row per person or group (a user, an organisation group or a
project group, the same principal shape as an owner), unique per engagement and deleted with
it. Existing facilitators are copied across before the columns are dropped. The downgrade
keeps the first-listed facilitator of each engagement.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0088"
down_revision: str | None = "0087"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS engagement_facilitators (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            engagement_id UUID NOT NULL REFERENCES engagements(id) ON DELETE CASCADE,
            sort_order INTEGER NOT NULL DEFAULT 0,
            facilitator_type VARCHAR(20) NOT NULL,
            facilitator_id UUID NOT NULL,
            CONSTRAINT ck_facilitator_principal CHECK (facilitator_type IN ('user', 'org_group', 'project_group')),
            CONSTRAINT uq_engagement_facilitators_principal UNIQUE (engagement_id, facilitator_type, facilitator_id)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_engagement_facilitators_engagement_id ON engagement_facilitators (engagement_id)")
    # Guarded: a database whose `engagements` table was built from the current models (the test suite's
    # `create_all`) never had the old columns, so there is nothing to copy.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = current_schema() AND table_name = 'engagements' AND column_name = 'facilitator_id'
            ) THEN
                INSERT INTO engagement_facilitators (engagement_id, facilitator_type, facilitator_id)
                SELECT id, facilitator_type, facilitator_id FROM engagements WHERE facilitator_id IS NOT NULL
                ON CONFLICT DO NOTHING;
            END IF;
        END $$
        """
    )
    op.execute("ALTER TABLE engagements DROP CONSTRAINT IF EXISTS ck_facilitator_principal")
    op.execute("ALTER TABLE engagements DROP COLUMN IF EXISTS facilitator_type")
    op.execute("ALTER TABLE engagements DROP COLUMN IF EXISTS facilitator_id")


def downgrade() -> None:
    op.execute("ALTER TABLE engagements ADD COLUMN IF NOT EXISTS facilitator_type VARCHAR(20)")
    op.execute("ALTER TABLE engagements ADD COLUMN IF NOT EXISTS facilitator_id UUID")
    op.execute(
        """
        UPDATE engagements e SET facilitator_type = f.facilitator_type, facilitator_id = f.facilitator_id
        FROM (
            SELECT DISTINCT ON (engagement_id) engagement_id, facilitator_type, facilitator_id
            FROM engagement_facilitators ORDER BY engagement_id, sort_order, created_at, id
        ) f WHERE f.engagement_id = e.id
        """
    )
    op.execute(
        """
        ALTER TABLE engagements ADD CONSTRAINT ck_facilitator_principal CHECK (
            (facilitator_type IS NULL OR facilitator_type IN ('user', 'org_group', 'project_group'))
            AND (facilitator_type IS NULL) = (facilitator_id IS NULL)
        )
        """
    )
    op.execute("DROP TABLE IF EXISTS engagement_facilitators")
