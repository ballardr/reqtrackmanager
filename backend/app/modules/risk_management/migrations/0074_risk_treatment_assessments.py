"""Risk treatment assessments

Revision ID: 0074
Revises: 0073
Create Date: 2026-10-12

Adds `risk_treatment_assessments`: the per-link verdict on whether a mitigating/treating artefact
actually reduces a risk, keyed to `artefact_links` with a cascading FK so
deleting a link drops its verdict.

Also lets a Decision address a Risk: an organisation that already has the
"Addresses" link type (created by Decision Management, restricted to Pain Point
targets) is widened to accept `risk`. Seeds only create missing link types, so
without this an existing organisation could not link a Decision to a Risk.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0074"
down_revision: str | None = "0073"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS risk_treatment_assessments (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            link_id UUID NOT NULL UNIQUE REFERENCES artefact_links(id) ON DELETE CASCADE,
            risk_id UUID NOT NULL REFERENCES risks(id) ON DELETE CASCADE,
            status VARCHAR(30) NOT NULL DEFAULT 'proposed',
            assessed_by UUID NOT NULL REFERENCES users(id),
            assessed_at TIMESTAMPTZ NOT NULL,
            rationale TEXT NOT NULL DEFAULT ''
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_risk_treatment_assessments_risk_id ON risk_treatment_assessments (risk_id)")
    op.execute(
        """
        UPDATE requirement_link_type_definitions
        SET allowed_target_types = allowed_target_types || '["risk"]'::jsonb
        WHERE forward_name = 'Addresses'
          AND allowed_target_types IS NOT NULL
          AND NOT (allowed_target_types @> '["risk"]'::jsonb)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS risk_treatment_assessments")
