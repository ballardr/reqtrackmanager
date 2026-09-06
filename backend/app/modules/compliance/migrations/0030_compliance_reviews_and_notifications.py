"""Compliance scheduled reviews + notification reminder bookkeeping (compliance module Phase 10)

Revision ID: 0030
Revises: 0029
Create Date: 2026-09-06

Adds the two tables backing the Compliance Module's scheduled reviews
(docs/Compliance_Module_Requirements.md §17, §18, §28; docs/compliance-
module-plan.md Phase 10):

- `compliance_reviews` (`app.modules.compliance.models.ComplianceReview`) —
  either a standard-level or a project-level scheduled review; exactly one
  of `standard_id`/`project_compliance_id` is set (a `CHECK` constraint).
- `compliance_review_evidence_links` (`ComplianceReviewEvidenceLink`) — the
  many-to-many evidence linkage a review may carry (§17's "Notes/evidence
  associated with the review"), mirroring `compliance_evidence_requirement_
  links`'s own shape.

Also adds the reminder-already-sent bookkeeping columns Phase 10's
notification sweeps need, on three existing tables (`compliance_evidence`,
`compliance_required_action_assessments`, `project_compliances`) — see each
column's own comment in `models.py` for why each pair exists.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0030"
down_revision: str | None = "0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS compliance_reviews (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            standard_id UUID REFERENCES compliance_standards(id) ON DELETE CASCADE,
            project_compliance_id UUID REFERENCES project_compliances(id) ON DELETE CASCADE,
            frequency_label VARCHAR(100) NOT NULL,
            recurrence_days INTEGER,
            next_due_date DATE NOT NULL,
            owner_id UUID REFERENCES users(id),
            status VARCHAR(20) NOT NULL DEFAULT 'scheduled',
            notes TEXT NOT NULL DEFAULT '',
            outcome VARCHAR(20),
            completed_at TIMESTAMPTZ,
            completed_by UUID REFERENCES users(id),
            created_by UUID NOT NULL REFERENCES users(id),
            due_reminder_sent_at TIMESTAMPTZ,
            overdue_notified_at TIMESTAMPTZ,
            CONSTRAINT ck_compliance_reviews_exactly_one_owner
                CHECK ((standard_id IS NOT NULL) != (project_compliance_id IS NOT NULL))
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_compliance_reviews_standard_id ON compliance_reviews (standard_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_compliance_reviews_project_compliance_id "
        "ON compliance_reviews (project_compliance_id)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS compliance_review_evidence_links (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            evidence_id UUID NOT NULL REFERENCES compliance_evidence(id) ON DELETE CASCADE,
            review_id UUID NOT NULL REFERENCES compliance_reviews(id) ON DELETE CASCADE,
            linked_by UUID NOT NULL REFERENCES users(id),
            created_at TIMESTAMPTZ NOT NULL,
            UNIQUE (evidence_id, review_id)
        )
        """
    )

    op.execute(
        "ALTER TABLE compliance_evidence ADD COLUMN IF NOT EXISTS expiry_reminder_sent_at TIMESTAMPTZ"
    )
    op.execute(
        "ALTER TABLE compliance_evidence ADD COLUMN IF NOT EXISTS expiry_notified_at TIMESTAMPTZ"
    )
    op.execute(
        "ALTER TABLE compliance_required_action_assessments "
        "ADD COLUMN IF NOT EXISTS due_reminder_sent_at TIMESTAMPTZ"
    )
    op.execute(
        "ALTER TABLE compliance_required_action_assessments "
        "ADD COLUMN IF NOT EXISTS overdue_notified_at TIMESTAMPTZ"
    )
    op.execute(
        "ALTER TABLE project_compliances ADD COLUMN IF NOT EXISTS target_date_reminder_sent_at TIMESTAMPTZ"
    )
    op.execute(
        "ALTER TABLE project_compliances ADD COLUMN IF NOT EXISTS target_date_overdue_notified_at TIMESTAMPTZ"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE project_compliances DROP COLUMN IF EXISTS target_date_overdue_notified_at")
    op.execute("ALTER TABLE project_compliances DROP COLUMN IF EXISTS target_date_reminder_sent_at")
    op.execute("ALTER TABLE compliance_required_action_assessments DROP COLUMN IF EXISTS overdue_notified_at")
    op.execute("ALTER TABLE compliance_required_action_assessments DROP COLUMN IF EXISTS due_reminder_sent_at")
    op.execute("ALTER TABLE compliance_evidence DROP COLUMN IF EXISTS expiry_notified_at")
    op.execute("ALTER TABLE compliance_evidence DROP COLUMN IF EXISTS expiry_reminder_sent_at")
    op.execute("DROP TABLE IF EXISTS compliance_review_evidence_links")
    op.execute("DROP TABLE IF EXISTS compliance_reviews")
