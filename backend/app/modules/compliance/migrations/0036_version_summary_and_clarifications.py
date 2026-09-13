"""Version summary + post-publish clarification tracking (compliance module Phase 24)

Revision ID: 0036
Revises: 0035
Create Date: 2026-09-09

Adds the two schema changes docs/compliance-module-plan.md's Phase 24 needs
(docs/Compliance_Module_Requirements.md §4, §31 — the human-review request
that a published version remain editable for clarifications/minor updates,
fully tracked, and that a version's own description/summary be editable at
any time):

- `compliance_standard_versions.summary` — a version's own current-standing
  description, distinct from the existing `change_note` (what changed
  *relative to the previous version*). Editable at any lifecycle stage; see
  `models.py`'s own Phase 24 design-decisions section.
- Four new columns on `compliance_requirements` recording the most recent
  post-publish clarification made to a requirement's wording:
  `clarification_count`, `last_clarified_at`, `last_clarified_by`,
  `last_clarification_note` — mirrors `project_compliance_requirements.
  decision_note`'s already-established "last decision's note lives on the
  row; full history is the audit trail" precedent, not a new table. Every
  clarification is also logged via `services.audit.log_event` (action
  `"clarified"`).

This migration adds no data of its own beyond column defaults — no existing
row's behaviour changes as a result of this migration alone.
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
