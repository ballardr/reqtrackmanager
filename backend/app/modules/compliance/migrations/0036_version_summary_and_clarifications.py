"""Version summary + post-publish clarification tracking

Revision ID: 0036
Revises: 0035
Create Date: 2026-09-09

Adds the schema for editing a published version for clarifications and minor updates, fully tracked (§4, §31):

- `compliance_standard_versions.summary`: a version's current-standing description, distinct from `change_note` (what
  changed relative to the previous version); editable at any lifecycle stage.
- Four columns on `compliance_requirements` recording the latest post-publish clarification: `clarification_count`,
  `last_clarified_at`, `last_clarified_by`, `last_clarification_note`. The last note lives on the row and the full
  history is the audit trail (`services.audit.log_event`, action `"clarified"`), as for `decision_note`.

No data changes beyond column defaults.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0036"
down_revision: str | None = "0035"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE compliance_standard_versions "
        "ADD COLUMN IF NOT EXISTS summary TEXT NOT NULL DEFAULT ''"
    )
    op.execute(
        "ALTER TABLE compliance_requirements "
        "ADD COLUMN IF NOT EXISTS clarification_count INTEGER NOT NULL DEFAULT 0"
    )
    op.execute(
        "ALTER TABLE compliance_requirements "
        "ADD COLUMN IF NOT EXISTS last_clarified_at TIMESTAMPTZ"
    )
    op.execute(
        "ALTER TABLE compliance_requirements "
        "ADD COLUMN IF NOT EXISTS last_clarified_by UUID REFERENCES users(id)"
    )
    op.execute(
        "ALTER TABLE compliance_requirements "
        "ADD COLUMN IF NOT EXISTS last_clarification_note TEXT NOT NULL DEFAULT ''"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE compliance_requirements DROP COLUMN IF EXISTS last_clarification_note")
    op.execute("ALTER TABLE compliance_requirements DROP COLUMN IF EXISTS last_clarified_by")
    op.execute("ALTER TABLE compliance_requirements DROP COLUMN IF EXISTS last_clarified_at")
    op.execute("ALTER TABLE compliance_requirements DROP COLUMN IF EXISTS clarification_count")
    op.execute("ALTER TABLE compliance_standard_versions DROP COLUMN IF EXISTS summary")
