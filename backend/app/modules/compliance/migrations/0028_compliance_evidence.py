"""Compliance evidence

Revision ID: 0028
Revises: 0027
Create Date: 2026-09-05

Adds the five tables of evidence support (§13-§15), built on the project assessment layer without modifying it:

- `compliance_evidence` (`ComplianceEvidence`): one project's own supporting evidence (§13).
- `compliance_evidence_revalidations` (`ComplianceEvidenceRevalidation`): append-only revalidation history (§15).
- `compliance_evidence_files` (`ComplianceEvidenceFile`): links a file (direct upload or organisation shared resource)
  to evidence through `services.files.upload_file`'s storage (§13).
- `compliance_evidence_requirement_links` and `compliance_evidence_action_links`: the many-to-many linkage that lets one
  piece of evidence support several `ProjectComplianceRequirement` and `ComplianceRequiredActionAssessment` rows (§13).

The tables start empty. `compliance_evidence` is created first; its four children each reference it.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0028"
down_revision: str | None = "0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS compliance_evidence (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            title VARCHAR(255) NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            issuing_organisation VARCHAR(255),
            issued_date DATE,
            expiry_date DATE,
            provided_by UUID NOT NULL REFERENCES users(id),
            provided_at TIMESTAMPTZ NOT NULL,
            notes TEXT NOT NULL DEFAULT '',
            is_archived BOOLEAN NOT NULL DEFAULT false,
            archived_at TIMESTAMPTZ,
            archived_by UUID REFERENCES users(id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_compliance_evidence_project_id "
        "ON compliance_evidence (project_id)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS compliance_evidence_revalidations (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            evidence_id UUID NOT NULL REFERENCES compliance_evidence(id) ON DELETE CASCADE,
            revalidated_by UUID NOT NULL REFERENCES users(id),
            revalidated_at TIMESTAMPTZ NOT NULL,
            previous_expiry_date DATE,
            new_expiry_date DATE,
            justification TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_compliance_evidence_revalidations_evidence_id "
        "ON compliance_evidence_revalidations (evidence_id)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS compliance_evidence_files (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            evidence_id UUID NOT NULL REFERENCES compliance_evidence(id) ON DELETE CASCADE,
            file_id UUID NOT NULL REFERENCES file_assets(id) ON DELETE CASCADE,
            linked_by UUID NOT NULL REFERENCES users(id),
            created_at TIMESTAMPTZ NOT NULL,
            UNIQUE (evidence_id, file_id)
        )
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS compliance_evidence_requirement_links (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            evidence_id UUID NOT NULL REFERENCES compliance_evidence(id) ON DELETE CASCADE,
            project_compliance_requirement_id UUID NOT NULL
                REFERENCES project_compliance_requirements(id) ON DELETE CASCADE,
            linked_by UUID NOT NULL REFERENCES users(id),
            created_at TIMESTAMPTZ NOT NULL,
            UNIQUE (evidence_id, project_compliance_requirement_id)
        )
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS compliance_evidence_action_links (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            evidence_id UUID NOT NULL REFERENCES compliance_evidence(id) ON DELETE CASCADE,
            required_action_assessment_id UUID NOT NULL
                REFERENCES compliance_required_action_assessments(id) ON DELETE CASCADE,
            linked_by UUID NOT NULL REFERENCES users(id),
            created_at TIMESTAMPTZ NOT NULL,
            UNIQUE (evidence_id, required_action_assessment_id)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS compliance_evidence_action_links")
    op.execute("DROP TABLE IF EXISTS compliance_evidence_requirement_links")
    op.execute("DROP TABLE IF EXISTS compliance_evidence_files")
    op.execute("DROP TABLE IF EXISTS compliance_evidence_revalidations")
    op.execute("DROP TABLE IF EXISTS compliance_evidence")
