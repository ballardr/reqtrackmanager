"""Traceability links between core Requirements and ComplianceRequirements

Revision ID: 0038
Revises: 0037
Create Date: 2026-09-13

Adds `compliance_requirement_traceability_links` (`ComplianceRequirementTraceabilityLink`, see `models.py`) so a core
Requirement can be traced to a compliance standard requirement. `requirement_id` references core's `requirements` table
(a module may depend on core; core never depends on a module's tables), `compliance_requirement_id` this module's
`compliance_requirements`, and `link_type_id` reuses core's organisation-scoped `requirement_link_type_definitions`
rather than a second type table.

No data changes.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0038"
down_revision: str | None = "0037"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
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
        "CREATE INDEX IF NOT EXISTS "
        "ix_compliance_requirement_traceability_links_requirement_id "
        "ON compliance_requirement_traceability_links (requirement_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_compliance_req_traceability_links_creq_id "
        "ON compliance_requirement_traceability_links (compliance_requirement_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS compliance_requirement_traceability_links")
