"""Standard applicability defaults, exceptions, and PM assignment

Revision ID: 0033
Revises: 0032
Create Date: 2026-09-08

Adds the schema of applicability defaults (§3, §7, §11, §26):

- `compliance_standards.applicability_default`: `VARCHAR(30) NOT NULL DEFAULT 'opt_in'`, so every existing standard keeps
  manual per-project assignment (see `models.py` and `enums.ComplianceStandardApplicabilityDefault`).
- `compliance_standard_default_exclusions` (`ComplianceStandardDefaultExclusion`): the "except" list of projects
  excluded from a standard's `applies_to_all_projects` default, with a mandatory `reason` (enforced by the API).

No data changes beyond the column default.
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
