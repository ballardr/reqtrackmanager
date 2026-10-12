"""Risk reviews and reassessment scheduling (Module 3 Phase 4)

Revision ID: 0075
Revises: 0074
Create Date: 2026-10-12

Adds `risk_reviews` (docs/plans/module-03-risk-management-plan.md Phase 4): an
immutable record of each periodic review with a snapshot of the ratings it was
made against. Also adds the two per-risk columns that make the review-due sweep
notify once per scheduled date, and `reassessment_reason` on treatment
assessments (why a verdict was sent back for reassessment).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0075"
down_revision: str | None = "0074"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS risk_reviews (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            risk_id UUID NOT NULL REFERENCES risks(id) ON DELETE CASCADE,
            risk_version_number INTEGER NOT NULL,
            reviewed_by UUID NOT NULL REFERENCES users(id),
            reviewed_at TIMESTAMPTZ NOT NULL,
            outcome VARCHAR(20) NOT NULL,
            notes TEXT NOT NULL,
            risk_status VARCHAR(30) NOT NULL,
            inherent_rating_label VARCHAR(100),
            inherent_rating_score DOUBLE PRECISION,
            residual_rating_label VARCHAR(100),
            residual_rating_score DOUBLE PRECISION,
            effective_treatment_count INTEGER NOT NULL DEFAULT 0,
            scheduled_for DATE,
            next_review_date DATE
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_risk_reviews_risk_id ON risk_reviews (risk_id)")
    op.execute("ALTER TABLE risks ADD COLUMN IF NOT EXISTS review_due_notified_for DATE")
    op.execute("ALTER TABLE risks ADD COLUMN IF NOT EXISTS review_overdue_notified_for DATE")
    op.execute("ALTER TABLE risk_treatment_assessments ADD COLUMN IF NOT EXISTS reassessment_reason TEXT NOT NULL DEFAULT ''")


def downgrade() -> None:
    op.execute("ALTER TABLE risk_treatment_assessments DROP COLUMN IF EXISTS reassessment_reason")
    op.execute("ALTER TABLE risks DROP COLUMN IF EXISTS review_overdue_notified_for")
    op.execute("ALTER TABLE risks DROP COLUMN IF EXISTS review_due_notified_for")
    op.execute("DROP TABLE IF EXISTS risk_reviews")
