"""Compliance traceability links onto the generic ArtefactLink table (Platform Enhancements Phase 6c)

Revision ID: 0069
Revises: 0068
Create Date: 2026-10-11

Moves every `compliance_requirement_traceability_links` row (a core requirement
-> a Compliance standard's clause, Compliance Phase 34) into core `artefact_links`
as `source_type='requirement'` -> `target_type='compliance_requirement'`, keeping
the row id, link type, creator and timestamps, then drops the table. Links were
polymorphic and any-to-any by the time this ran (Module 0 Phase 3, Platform
Enhancements Phase 5b), so the module-private table no longer had a reason to
exist; with it gone the Links panel, the link graph, link-type rules, hiding and
delete-in-use, change requests and project bundles all see these links.

A traceability link joins records of one organisation (the clause's standard
belongs to the requirement's project's organisation), is same-project from the
requirement's side, and has no cross-level project columns, so
`source_project_id` / `target_project_id` stay NULL.

The downgrade recreates the table and copies the rows back (ids preserved).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0069"
down_revision: str | None = "0068"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO artefact_links
            (id, created_at, updated_at, source_type, source_id, target_type, target_id, link_type_id, created_by)
        SELECT
            t.id, t.created_at, t.updated_at, 'requirement', t.requirement_id,
            'compliance_requirement', t.compliance_requirement_id, t.link_type_id, t.created_by
        FROM compliance_requirement_traceability_links t
        WHERE NOT EXISTS (SELECT 1 FROM artefact_links al WHERE al.id = t.id)
        """
    )
    op.execute("DROP TABLE IF EXISTS compliance_requirement_traceability_links")


def downgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS compliance_requirement_traceability_links (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            requirement_id UUID NOT NULL REFERENCES requirements(id) ON DELETE CASCADE,
            compliance_requirement_id UUID NOT NULL REFERENCES compliance_requirements(id) ON DELETE CASCADE,
            link_type_id UUID NOT NULL REFERENCES requirement_link_type_definitions(id),
            created_by UUID NOT NULL REFERENCES users(id),
            CONSTRAINT uq_compliance_req_traceability_links_req_creq_type
                UNIQUE (requirement_id, compliance_requirement_id, link_type_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_compliance_requirement_traceability_links_requirement_id "
        "ON compliance_requirement_traceability_links (requirement_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_compliance_req_traceability_links_creq_id "
        "ON compliance_requirement_traceability_links (compliance_requirement_id)"
    )
    op.execute(
        """
        INSERT INTO compliance_requirement_traceability_links
            (id, created_at, updated_at, requirement_id, compliance_requirement_id, link_type_id, created_by)
        SELECT al.id, al.created_at, al.updated_at, al.source_id, al.target_id, al.link_type_id, al.created_by
        FROM artefact_links al
        WHERE al.source_type = 'requirement' AND al.target_type = 'compliance_requirement'
          AND al.link_type_id IS NOT NULL
          AND EXISTS (SELECT 1 FROM requirements r WHERE r.id = al.source_id)
          AND EXISTS (SELECT 1 FROM compliance_requirements c WHERE c.id = al.target_id)
        ON CONFLICT DO NOTHING
        """
    )
    op.execute(
        "DELETE FROM artefact_links WHERE source_type = 'requirement' AND target_type = 'compliance_requirement'"
    )
