"""Compliance evidence links onto the generic ArtefactLink table

Revision ID: 0043
Revises: 0042
Create Date: 2026-09-21

Replaces `compliance_evidence_requirement_links` (Evidence to ProjectComplianceRequirement) and
`compliance_evidence_action_links` (Evidence to ComplianceRequiredActionAssessment) with rows in core `artefact_links`
(`ArtefactLink`), as migration 0041 did for `requirement_links` and `requirement_action_links`.

Column widening: `artefact_links.source_type` and `target_type` are widened from `VARCHAR(20)` to `VARCHAR(40)` first,
because this module's artefact types are longer (`compliance_required_action_assessment` is 37 characters).

Column mapping:
- `compliance_evidence_requirement_links` row -> `source_type='compliance_evidence'`, `source_id=evidence_id`,
  `target_type='project_compliance_requirement'`, `target_id=project_compliance_requirement_id`, `link_type_id=NULL`,
  `created_by=linked_by`, `created_at` preserved, `updated_at=created_at` (the table had no `updated_at`).
- `compliance_evidence_action_links` row -> `source_type='compliance_evidence'`, `source_id=evidence_id`,
  `target_type='compliance_required_action_assessment'`, `target_id=required_action_assessment_id`,
  `link_type_id=NULL`, `created_by=linked_by`, timestamps as above.

Row ids are preserved (`INSERT ... SELECT id, ...`), as in migration 0041.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0043"
down_revision: str | None = "0042"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- 1. Widen artefact_links.source_type/target_type ------------------

    op.execute("ALTER TABLE artefact_links ALTER COLUMN source_type TYPE VARCHAR(40)")
    op.execute("ALTER TABLE artefact_links ALTER COLUMN target_type TYPE VARCHAR(40)")

    # --- 2. Backfill from compliance_evidence_requirement_links -----------

    op.execute(
        """
        INSERT INTO artefact_links
            (id, created_at, updated_at, source_type, source_id, target_type, target_id, link_type_id, created_by)
        SELECT
            l.id, l.created_at, l.created_at, 'compliance_evidence', l.evidence_id,
            'project_compliance_requirement', l.project_compliance_requirement_id, NULL, l.linked_by
        FROM compliance_evidence_requirement_links l
        WHERE NOT EXISTS (SELECT 1 FROM artefact_links al WHERE al.id = l.id)
        """
    )

    # --- 3. Backfill from compliance_evidence_action_links -----------------

    op.execute(
        """
        INSERT INTO artefact_links
            (id, created_at, updated_at, source_type, source_id, target_type, target_id, link_type_id, created_by)
        SELECT
            l.id, l.created_at, l.created_at, 'compliance_evidence', l.evidence_id,
            'compliance_required_action_assessment', l.required_action_assessment_id, NULL, l.linked_by
        FROM compliance_evidence_action_links l
        WHERE NOT EXISTS (SELECT 1 FROM artefact_links al WHERE al.id = l.id)
        """
    )

    # --- 4. Drop the old tables ---------------------------------------------

    op.execute("DROP TABLE IF EXISTS compliance_evidence_requirement_links")
    op.execute("DROP TABLE IF EXISTS compliance_evidence_action_links")


def downgrade() -> None:
    # Recreate both old tables in their final pre-drop shape.
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

    # Reverse-backfill, preserving ids.
    op.execute(
        """
        INSERT INTO compliance_evidence_requirement_links
            (id, evidence_id, project_compliance_requirement_id, linked_by, created_at)
        SELECT al.id, al.source_id, al.target_id, al.created_by, al.created_at
        FROM artefact_links al
        WHERE al.source_type = 'compliance_evidence' AND al.target_type = 'project_compliance_requirement'
        """
    )
    op.execute(
        """
        INSERT INTO compliance_evidence_action_links
            (id, evidence_id, required_action_assessment_id, linked_by, created_at)
        SELECT al.id, al.source_id, al.target_id, al.created_by, al.created_at
        FROM artefact_links al
        WHERE al.source_type = 'compliance_evidence' AND al.target_type = 'compliance_required_action_assessment'
        """
    )

    # Remove the now-duplicated rows from artefact_links before narrowing
    # its columns back — a column can't shrink below its widest current
    # value.
    op.execute(
        """
        DELETE FROM artefact_links
        WHERE source_type = 'compliance_evidence'
            AND target_type IN ('project_compliance_requirement', 'compliance_required_action_assessment')
        """
    )
    op.execute("ALTER TABLE artefact_links ALTER COLUMN source_type TYPE VARCHAR(20)")
    op.execute("ALTER TABLE artefact_links ALTER COLUMN target_type TYPE VARCHAR(20)")
