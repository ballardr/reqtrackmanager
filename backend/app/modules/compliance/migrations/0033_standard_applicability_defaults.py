"""Standard applicability defaults, exceptions, and PM assignment (compliance module Phase 20)

Revision ID: 0033
Revises: 0032
Create Date: 2026-09-08

Adds the two things docs/compliance-module-plan.md's Phase 20 needs
(docs/Compliance_Module_Requirements.md §3, §7, §11, §26):

- `compliance_standards.applicability_default` — a new `VARCHAR(30)` column,
  `NOT NULL DEFAULT 'opt_in'`, so every existing standard (including the
  seeded `ASA-1`) keeps today's fully-manual, per-project assignment
  behaviour unchanged. See `models.py`'s own Phase 20 design-decisions
  section and `enums.py::ComplianceStandardApplicabilityDefault`.
- `compliance_standard_default_exclusions`
  (`app.modules.compliance.models.ComplianceStandardDefaultExclusion`) — the
  "...except" list of projects excepted out of a standard's
  `applies_to_all_projects` default, with a mandatory `reason` (enforced at
  the API layer, same as every other mandatory-justification field in this
  module).

This migration adds no data of its own beyond the column default — no
existing `ProjectCompliance` rows are touched, and no organisation's
existing standards change behaviour as a result of this migration alone.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0033"
down_revision: str | None = "0032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE compliance_standards "
        "ADD COLUMN IF NOT EXISTS applicability_default VARCHAR(30) NOT NULL DEFAULT 'opt_in'"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS compliance_standard_default_exclusions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            standard_id UUID NOT NULL REFERENCES compliance_standards(id) ON DELETE CASCADE,
            project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            excluded_by UUID NOT NULL REFERENCES users(id),
            excluded_at TIMESTAMPTZ NOT NULL,
            reason TEXT NOT NULL DEFAULT '',
            UNIQUE (standard_id, project_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_compliance_standard_default_exclusions_standard_id "
        "ON compliance_standard_default_exclusions (standard_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_compliance_standard_default_exclusions_project_id "
        "ON compliance_standard_default_exclusions (project_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS compliance_standard_default_exclusions")
    op.execute("ALTER TABLE compliance_standards DROP COLUMN IF EXISTS applicability_default")
