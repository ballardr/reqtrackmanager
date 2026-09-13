"""Traceability links between core Requirements and ComplianceRequirements (compliance module Phase 34)

Revision ID: 0038
Revises: 0037
Create Date: 2026-09-13

Adds `compliance_requirement_traceability_links` (`ComplianceRequirement
TraceabilityLink`, `models.py`) — docs/compliance-module-plan.md Phase 34's
"I can't add a traceability link between a core Requirement and a
compliance standard requirement" gap. `requirement_id` reaches into core's
own `requirements` table (a module depending on core is fine; core must
never depend back on a module's own tables, per CLAUDE.md's "Modular
Feature System Boundary" — see `models.py`'s own Phase 34 notes),
`compliance_requirement_id` into this module's own `compliance_requirements`,
and `link_type_id` reuses core's existing, org-scoped
`requirement_link_type_definitions` vocabulary rather than a second,
compliance-only type table.

This migration adds no data of its own — no existing row's behaviour
changes as a result of this migration alone.
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
            UNIQUE (requirement_id, compliance_requirement_id, link_type_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_compliance_req_traceability_links_requirement_id "
        "ON compliance_requirement_traceability_links (requirement_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_compliance_req_traceability_links_compliance_requirement_id "
        "ON compliance_requirement_traceability_links (compliance_requirement_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS compliance_requirement_traceability_links")
