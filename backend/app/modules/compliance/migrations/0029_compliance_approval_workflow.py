"""Compliance approval / sign-off workflow

Revision ID: 0029
Revises: 0028
Create Date: 2026-09-06

Adds the columns of the approval and sign-off decision step (§12, §16, §27) beside `approval_state` on
`ProjectComplianceRequirement`: `approved_decided_at`, `approval_decided_by` (§12 "Date/time of approval", "Who
approved/signed off") and `decision_note` (one column serving both approve and reject, see `models.py`).

No new table: §12's approval history is the existing `audit_events` table.
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
