"""Compliance evidence links onto the generic ArtefactLink table (Module 0 — Platform Foundations, Phase 3)

Revision ID: 0043
Revises: 0042
Create Date: 2026-09-21

Replaces this module's own `compliance_evidence_requirement_links`
(`ComplianceEvidenceRequirementLink` — Evidence<->ProjectComplianceRequirement)
and `compliance_evidence_action_links` (`ComplianceEvidenceActionLink` —
Evidence<->ComplianceRequiredActionAssessment) tables with rows in the core
`artefact_links` table (`app.models.relationship.ArtefactLink`), mirroring
exactly how core migration 0041 retired `requirement_links`/
`requirement_action_links` — this module's own two evidence-link tables
were, per their own original docstrings, "deliberately owned by this
module, not core" only because no shared relationship infrastructure
existed yet when Phase 8 built them; this migration is that gap closing,
per `docs/plans/module-00-platform-foundations-plan.md`'s Phase 3.

**Column widening**: `artefact_links.source_type`/`target_type` were
`VARCHAR(20)`, sized for the two core `ArtefactType` values only. This
module's own artefact-type values (`app.modules.compliance.module.
MODULE_DEFINITION.artefact_types`) are wider — the longest,
`compliance_required_action_assessment`, is 37 characters — so both
columns are widened to `VARCHAR(40)` first.

**Column mapping**:

- `compliance_evidence_requirement_links` row -> `source_type=
  'compliance_evidence'`, `source_id=evidence_id`, `target_type=
  'project_compliance_requirement'`, `target_id=
  project_compliance_requirement_id`, `link_type_id=NULL` (this table
  never had a type, exactly like the old `requirement_action_links`),
  `created_by=linked_by`, `created_at` preserved, `updated_at=created_at`
  (this table had no separate `updated_at` column, same as
  `requirement_action_links`).
- `compliance_evidence_action_links` row -> `source_type=
  'compliance_evidence'`, `source_id=evidence_id`, `target_type=
  'compliance_required_action_assessment'`, `target_id=
  required_action_assessment_id`, `link_type_id=NULL`, `created_by=
  linked_by`, `created_at`/`updated_at` as above.

**Row ids preserved** across the backfill (`INSERT ... SELECT id, ...`),
matching migration 0041's own precedent, even though a full-codebase grep
found no external FK referencing either old table's `id` column — free,
and consistent.

No application code changes ship in this migration file — `service.py`,
`reports.py`, `export.py`, and `project_router.py` were repointed onto
`app.services.relationships` in the same commit; see `docs/decisions.md`'s
"Module 0 (Platform Foundations) Phase 3" entry for the full call-site
list.
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
