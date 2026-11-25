"""Backfill default compliance action types

Revision ID: 0032
Revises: 0031
Create Date: 2026-09-08

Backfills default `compliance_action_type_definitions` rows for organisations that existed before new organisations were
seeded at creation (`service.seed_compliance_action_types`, called from `routers.orgs.create_organization` and
`services.bootstrap`). Without them the "Add required action" control (`RequirementTree.tsx`) is unavailable until a
Compliance Manager creates an action type under Org Admin -> Compliance -> Action types.

One `INSERT ... SELECT ... WHERE NOT EXISTS` per organisation, as migration 0012 does for `action_type_definitions`; it
is a no-op on a database created from the current models (no organisations yet). The names match
`service.DEFAULT_COMPLIANCE_ACTION_TYPES` and `backend/scripts/seed_demo_data.py`.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0032"
down_revision: str | None = "0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO compliance_action_type_definitions (id, created_at, updated_at, organization_id, name, sort_order)
        SELECT gen_random_uuid(), now(), now(), o.id, v.name, v.sort_order
        FROM organizations o
        CROSS JOIN (VALUES ('Document Review', 0), ('Test', 1)) AS v(name, sort_order)
        WHERE NOT EXISTS (
            SELECT 1 FROM compliance_action_type_definitions catd
            WHERE catd.organization_id = o.id AND catd.name = v.name
        )
        """
    )


def downgrade() -> None:
    # No-op: this migration only backfills rows into a table migration 0026 created, and a deleted row cannot be told
    # from one a person created with the same name or one already assigned to a required action.
    pass
