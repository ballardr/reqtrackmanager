"""Backfill default compliance action types (Phase 17c)

Revision ID: 0032
Revises: 0031
Create Date: 2026-09-08

Compliance shipped with no default `compliance_action_type_definitions`
rows for any organisation — a brand-new org's "Add required action" control
(`RequirementTree.tsx`) is greyed out until a Compliance Manager first
visits Org Admin -> Compliance -> Action types and creates one by hand, the
same class of gap migration 0012 already closed once for the generic,
project-scoped `action_type_definitions` (`DEFAULT_ACTION_TYPES`).

Going forward, every new organisation gets these seeded at creation time by
`app.modules.compliance.service.seed_compliance_action_types`, called from
`routers.orgs.create_organization` and `services.bootstrap` (see that
function's own docstring for why organisation-creation time, not a
module-enablement hook, is where this has to run). This migration is the
one-time backfill for every organisation that already existed before that
seeding call was added — mirrors 0012's own
`action_type_definitions`/`project_status_definitions`/
`requirement_link_type_definitions` backfill pattern exactly: an
`INSERT ... SELECT ... WHERE NOT EXISTS` per organisation, safe to run
unconditionally (a fresh database created straight from current models via
0001's `create_all()` has no organisations yet at this point in its own
migration history, so this is a no-op there; an already-migrated database
gets exactly the rows it was always missing).

Names match what `backend/scripts/seed_demo_data.py` already invented by
hand for its own compliance demo data ("Document Review", "Test") — see
`app.modules.compliance.service.DEFAULT_COMPLIANCE_ACTION_TYPES`.
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
    # Deliberately a no-op: this migration only backfills rows into a table
    # migration 0026 already created, it doesn't create the table itself,
    # so there's no matching structural change to reverse. Deleting the
    # backfilled rows here would be both ambiguous (an already-renamed or
    # since-deleted-and-recreated same-named row is indistinguishable from
    # one this migration inserted) and destructive if any required action
    # has since been assigned one of them.
    pass
