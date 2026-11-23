"""Let persona/stakeholder type references cascade away with their org/project

Revision ID: 0060
Revises: 0059
Create Date: 2026-10-05

`persona_versions` type references become `ON DELETE SET NULL` (as do
`stakeholder_versions`, idempotently), so deleting an organisation or project
does not depend on cascade order. In-use types are protected by the service layer.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0060"
down_revision: str | None = "0059"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FKS = (
    ("persona_versions", "persona_versions_org_type_id_fkey", "org_type_id", "persona_type_definitions"),
    ("persona_versions", "persona_versions_project_type_id_fkey", "project_type_id", "project_persona_types"),
    ("stakeholder_versions", "stakeholder_versions_org_type_id_fkey", "org_type_id", "stakeholder_type_definitions"),
    ("stakeholder_versions", "stakeholder_versions_project_type_id_fkey", "project_type_id", "project_stakeholder_types"),
)


def _recreate(on_delete: str) -> None:
    for table, name, column, target in _FKS:
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {name}")
        op.execute(
            f"ALTER TABLE {table} ADD CONSTRAINT {name} FOREIGN KEY ({column}) REFERENCES {target}(id){on_delete}"
        )


def upgrade() -> None:
    _recreate(" ON DELETE SET NULL")


def downgrade() -> None:
    _recreate("")
