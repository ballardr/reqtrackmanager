"""Project compliance assessment (compliance module Phase 7)

Revision ID: 0027
Revises: 0026
Create Date: 2026-09-05

Adds the three tables backing the Compliance Module's project-specific
assessment layer (docs/Compliance_Module_Requirements.md §7-§11, §16, §20,
§25, §26; docs/compliance-module-plan.md Phase 7) — built on top of Phase
5/6's organisation-level standard definitions, never modifying them:

- `project_compliances` (`app.modules.compliance.models.ProjectCompliance`)
  — a project's assignment to one specific, always-published
  `compliance_standard_versions` row (§7).
- `project_compliance_requirements` (`ProjectComplianceRequirement`) — one
  project's per-requirement assessment (applicability, compliance status,
  justification, notes, assessment/applicability actor+timestamp pairs,
  and a `approval_state` column reserved for Phase 9) (§8-§10, §16, §20).
- `compliance_required_action_assessments`
  (`ComplianceRequiredActionAssessment`) — one project's per-required-action
  assessment (assignee, due date, completion overlay) (§6, §25).

All three tables start empty: rows are only ever created by the API when a
`ProjectCompliance` is assigned (which materialises every requirement's and
required action's assessment row for that assignment in the same
transaction), never by this migration. Table order below follows the FK
dependency chain: `project_compliances` first (references `projects` and
`compliance_standard_versions`, both already existing), then
`project_compliance_requirements` (references `project_compliances` and
`compliance_requirements`), then `compliance_required_action_assessments`
(references `project_compliance_requirements` and
`compliance_required_actions`).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0027"
down_revision: str | None = "0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS project_compliances (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            standard_version_id UUID NOT NULL REFERENCES compliance_standard_versions(id),
            assigned_at TIMESTAMPTZ NOT NULL,
            assigned_by UUID NOT NULL REFERENCES users(id),
            target_compliance_date DATE,
            is_archived BOOLEAN NOT NULL DEFAULT false,
            archived_at TIMESTAMPTZ,
            archived_by UUID REFERENCES users(id),
            UNIQUE (project_id, standard_version_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_project_compliances_project_id "
        "ON project_compliances (project_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_project_compliances_standard_version_id "
        "ON project_compliances (standard_version_id)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS project_compliance_requirements (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            project_compliance_id UUID NOT NULL REFERENCES project_compliances(id) ON DELETE CASCADE,
            requirement_id UUID NOT NULL REFERENCES compliance_requirements(id),
            explicit_applicability VARCHAR(20),
            justification TEXT NOT NULL DEFAULT '',
            notes TEXT NOT NULL DEFAULT '',
            compliance_status VARCHAR(20) NOT NULL DEFAULT 'not_started',
            assessed_at TIMESTAMPTZ,
            assessed_by UUID REFERENCES users(id),
            applicability_set_at TIMESTAMPTZ,
            applicability_set_by UUID REFERENCES users(id),
            approval_state VARCHAR(24) NOT NULL DEFAULT 'not_assessed',
            UNIQUE (project_compliance_id, requirement_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_project_compliance_requirements_project_compliance_id "
        "ON project_compliance_requirements (project_compliance_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_project_compliance_requirements_requirement_id "
        "ON project_compliance_requirements (requirement_id)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS compliance_required_action_assessments (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            project_compliance_requirement_id UUID NOT NULL
                REFERENCES project_compliance_requirements(id) ON DELETE CASCADE,
            required_action_id UUID NOT NULL REFERENCES compliance_required_actions(id),
            assignee_id UUID REFERENCES users(id),
            due_date DATE,
            is_completed BOOLEAN NOT NULL DEFAULT false,
            completed_at TIMESTAMPTZ,
            completed_by UUID REFERENCES users(id),
            notes TEXT NOT NULL DEFAULT '',
            UNIQUE (project_compliance_requirement_id, required_action_id)
        )
        """
    )
    # Explicit, shortened name — see `models.py`'s own comment on this index:
    # the auto-generated name for this column is 75 characters, over
    # Postgres's 63-byte identifier limit.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_required_action_assessments_pcr_id "
        "ON compliance_required_action_assessments (project_compliance_requirement_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_compliance_required_action_assessments_required_action_id "
        "ON compliance_required_action_assessments (required_action_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS compliance_required_action_assessments")
    op.execute("DROP TABLE IF EXISTS project_compliance_requirements")
    op.execute("DROP TABLE IF EXISTS project_compliances")
