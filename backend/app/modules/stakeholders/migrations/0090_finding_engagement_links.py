"""Findings are linked to their engagement (Module 2 Phase 5 follow-up)

Revision ID: 0090
Revises: 0089
Create Date: 2026-10-13

A finding now has a structural "Has finding" link from its engagement, made when the finding is, so
a trace from a Pain Point, Need or Open Question a finding raised reaches the engagement it came
from. This backfills the link for findings recorded before it existed: it creates the organisation's
"Has finding" / "Is a finding of" link type where missing (dedicated, so the generic link endpoints
neither offer nor delete it) and one link per finding that lacks one. The downgrade removes the links
and the link type; nothing else changes.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0090"
down_revision: str | None = "0089"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO requirement_link_type_definitions (
            id, created_at, updated_at, organization_id, forward_name, reverse_name, sort_order,
            allowed_source_types, allowed_target_types, dedicated_endpoint
        )
        SELECT gen_random_uuid(), now(), now(), o.organization_id, 'Has finding', 'Is a finding of',
               (SELECT count(*) FROM requirement_link_type_definitions t
                 WHERE t.organization_id = o.organization_id AND t.project_id IS NULL),
               '["engagement"]'::jsonb, '["research_finding"]'::jsonb, true
        FROM (
            SELECT DISTINCT p.organization_id
            FROM research_findings f JOIN projects p ON p.id = f.project_id
        ) o
        WHERE NOT EXISTS (
            SELECT 1 FROM requirement_link_type_definitions t
            WHERE t.organization_id = o.organization_id AND t.project_id IS NULL AND t.forward_name = 'Has finding'
        )
        """
    )
    op.execute(
        """
        INSERT INTO artefact_links (id, created_at, updated_at, source_type, source_id, target_type, target_id, link_type_id, created_by)
        SELECT gen_random_uuid(), now(), now(), 'engagement', f.engagement_id, 'research_finding', f.id, t.id, f.creator_id
        FROM research_findings f
        JOIN projects p ON p.id = f.project_id
        JOIN requirement_link_type_definitions t
          ON t.organization_id = p.organization_id AND t.project_id IS NULL AND t.forward_name = 'Has finding'
        WHERE NOT EXISTS (
            SELECT 1 FROM artefact_links l
            WHERE l.source_type = 'engagement' AND l.source_id = f.engagement_id
              AND l.target_type = 'research_finding' AND l.target_id = f.id AND l.link_type_id = t.id
        )
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM artefact_links WHERE link_type_id IN (
            SELECT id FROM requirement_link_type_definitions
            WHERE forward_name = 'Has finding' AND project_id IS NULL
        )
        """
    )
    op.execute("DELETE FROM requirement_link_type_definitions WHERE forward_name = 'Has finding' AND project_id IS NULL")
