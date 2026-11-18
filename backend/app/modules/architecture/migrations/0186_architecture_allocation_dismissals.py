"""System Architecture allocation dismissals

Revision ID: 0186
Revises: 0185
Create Date: 2026-11-14

Adds `architecture_allocation_dismissals`: one row per requirement and element whose suggested allocation (an
element placed in the requirement's component) a person dismissed. Deleting the requirement, the element or the
project removes the row. Nothing is seeded.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0186"
down_revision: str | None = "0185"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS architecture_allocation_dismissals (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            requirement_id UUID NOT NULL REFERENCES requirements(id) ON DELETE CASCADE,
            element_id UUID NOT NULL REFERENCES architecture_elements(id) ON DELETE CASCADE,
            dismissed_by UUID REFERENCES users(id) ON DELETE SET NULL,
            CONSTRAINT uq_architecture_allocation_dismissals_pair UNIQUE (requirement_id, element_id)
        )
        """
    )
    for column in ("project_id", "requirement_id", "element_id"):
        op.execute(
            f"CREATE INDEX IF NOT EXISTS ix_architecture_allocation_dismissals_{column} "
            f"ON architecture_allocation_dismissals ({column})"
        )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS architecture_allocation_dismissals")
