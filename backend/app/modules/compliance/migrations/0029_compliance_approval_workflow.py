"""Compliance approval / sign-off workflow (compliance module Phase 9)

Revision ID: 0029
Revises: 0028
Create Date: 2026-09-06

Adds the three columns `ProjectComplianceRequirement`'s approval/sign-off
decision step needs (docs/Compliance_Module_Requirements.md §12, §16, §27;
docs/compliance-module-plan.md Phase 9) on top of the `approval_state`
column Phase 7 already added: `approved_decided_at`/`approval_decided_by`
(§12's "Date/time of approval"/"Who approved/signed off the assessment")
and `decision_note` (rationale attached to an approve/reject decision — see
`models.py`'s own Phase 9 notes for why this is one column pair serving
both decisions, not two).

No new tables: §12's "Approval/sign-off history" is satisfied by the
existing `audit_events` table (already created), not a bespoke history
table — see `models.py`'s own Phase 9 notes.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0029"
down_revision: str | None = "0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE project_compliance_requirements "
        "ADD COLUMN IF NOT EXISTS approval_decided_at TIMESTAMPTZ"
    )
    op.execute(
        "ALTER TABLE project_compliance_requirements "
        "ADD COLUMN IF NOT EXISTS approval_decided_by UUID REFERENCES users(id)"
    )
    op.execute(
        "ALTER TABLE project_compliance_requirements "
        "ADD COLUMN IF NOT EXISTS decision_note TEXT NOT NULL DEFAULT ''"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE project_compliance_requirements DROP COLUMN IF EXISTS decision_note")
    op.execute("ALTER TABLE project_compliance_requirements DROP COLUMN IF EXISTS approval_decided_by")
    op.execute("ALTER TABLE project_compliance_requirements DROP COLUMN IF EXISTS approval_decided_at")
