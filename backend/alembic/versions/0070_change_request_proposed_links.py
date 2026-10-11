"""Links proposed on change requests (Platform Enhancements Phase 6b)

Revision ID: 0070
Revises: 0069
Create Date: 2026-10-11

Adds `change_request_proposed_links`: the links a change request proposes, merged
into the requirement on approval as the approver chooses. A real table with a
foreign key to the link type (not a JSON list) so deleting an in-use link type
can repoint or block on them.

`ADD_LINK` becomes the one-link case of the same mechanism: each existing
`change_request_versions` row carrying `proposed_link_target_requirement_id` is
copied in (an outgoing link to a requirement of the request's own project) and
the two ADD_LINK columns are dropped. Outcomes of existing requests are
reconstructed: an open request's link is `pending`; an approved one is `merged`
when the link exists and `skipped` otherwise (approval re-checked the link and
may have dropped it, and that was never recorded); a rejected or withdrawn one is
`declined`. A pending row whose link type was already stripped (`SET NULL`) is
`skipped`, since it could no longer be applied.

The downgrade restores the two columns from each ADD_LINK request's first
proposed link (a request with several loses the extras) and drops the table.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0070"
down_revision: str | None = "0069"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS change_request_proposed_links (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            change_request_version_id UUID NOT NULL REFERENCES change_request_versions(id) ON DELETE CASCADE,
            link_type_id UUID REFERENCES requirement_link_type_definitions(id) ON DELETE SET NULL,
            direction VARCHAR(10) NOT NULL,
            other_type VARCHAR(40) NOT NULL,
            other_id UUID NOT NULL,
            other_project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
            outcome VARCHAR(20) NOT NULL DEFAULT 'pending',
            outcome_reason TEXT,
            sort_order INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_cr_proposed_links_version ON change_request_proposed_links (change_request_version_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_cr_proposed_links_link_type ON change_request_proposed_links (link_type_id)"
    )
    op.execute(
        """
        INSERT INTO change_request_proposed_links
            (id, change_request_version_id, link_type_id, direction, other_type, other_id, outcome, outcome_reason, sort_order)
        SELECT
            gen_random_uuid(), v.id, v.proposed_link_type_id, 'outgoing', 'requirement',
            v.proposed_link_target_requirement_id,
            CASE
                WHEN cr.status IN ('rejected', 'withdrawn') THEN 'declined'
                WHEN cr.status = 'approved' AND EXISTS (
                    SELECT 1 FROM artefact_links al
                    WHERE al.source_type = 'requirement' AND al.source_id = cr.requirement_id
                      AND al.target_type = 'requirement' AND al.target_id = v.proposed_link_target_requirement_id
                      AND al.link_type_id = v.proposed_link_type_id
                ) THEN 'merged'
                WHEN cr.status = 'approved' THEN 'skipped'
                WHEN v.proposed_link_type_id IS NULL THEN 'skipped'
                ELSE 'pending'
            END,
            CASE
                WHEN cr.status = 'approved' AND NOT EXISTS (
                    SELECT 1 FROM artefact_links al
                    WHERE al.source_type = 'requirement' AND al.source_id = cr.requirement_id
                      AND al.target_type = 'requirement' AND al.target_id = v.proposed_link_target_requirement_id
                      AND al.link_type_id = v.proposed_link_type_id
                ) THEN 'No longer valid when the request was approved.'
                WHEN cr.status NOT IN ('approved', 'rejected', 'withdrawn') AND v.proposed_link_type_id IS NULL
                    THEN 'The link type no longer exists.'
                ELSE NULL
            END,
            0
        FROM change_request_versions v
        JOIN change_requests cr ON cr.id = v.change_request_id
        WHERE cr.kind = 'add_link' AND v.proposed_link_target_requirement_id IS NOT NULL
        """
    )
    op.execute("ALTER TABLE change_request_versions DROP COLUMN IF EXISTS proposed_link_target_requirement_id")
    op.execute("ALTER TABLE change_request_versions DROP COLUMN IF EXISTS proposed_link_type_id")


def downgrade() -> None:
    op.execute(
        "ALTER TABLE change_request_versions "
        "ADD COLUMN IF NOT EXISTS proposed_link_target_requirement_id UUID REFERENCES requirements(id) ON DELETE SET NULL, "
        "ADD COLUMN IF NOT EXISTS proposed_link_type_id UUID REFERENCES requirement_link_type_definitions(id) ON DELETE SET NULL"
    )
    op.execute(
        """
        UPDATE change_request_versions v
        SET proposed_link_target_requirement_id = p.other_id, proposed_link_type_id = p.link_type_id
        FROM (
            SELECT DISTINCT ON (change_request_version_id) change_request_version_id, other_id, link_type_id
            FROM change_request_proposed_links
            WHERE other_type = 'requirement' AND direction = 'outgoing'
            ORDER BY change_request_version_id, sort_order
        ) p
        WHERE p.change_request_version_id = v.id
          AND EXISTS (SELECT 1 FROM requirements r WHERE r.id = p.other_id)
        """
    )
    op.execute("DROP TABLE IF EXISTS change_request_proposed_links")
