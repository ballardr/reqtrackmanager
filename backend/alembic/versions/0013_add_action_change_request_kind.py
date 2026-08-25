"""Add-action change request kind

Revision ID: 0013
Revises: 0012
Create Date: 2026-08-25

2026-08 UX audit roadmap item 514: actions had no draft/change-request gate
the way a requirement's own fields do (`services.requirements.
LOCKED_STATUSES`) — once a requirement is APPROVED/COMPLETED, creating or
linking an action still went straight through with no review step, unlike
every other requirement field. Adds a new `ADD_ACTION` `ChangeRequestKind`
(a plain VARCHAR `str_enum` column — no migration needed for the enum value
itself, same reasoning as 0012's own note on `ReviewTargetType.ACTION`) and
six new nullable columns on `change_request_versions` carrying the proposed
action's content: either `proposed_action_link_id` (link an existing
`RequirementAction`) or `proposed_action_title` + `proposed_action_type_id`
(create a new one), mutually exclusive — see
`routers/change_requests.py::create_change_request`'s validation.

All-nullable additive columns, so every existing `change_request_versions`
row is unaffected (`NULL` on backfill, correct for a MODIFY_REQUIREMENT/
NEW_REQUIREMENT version that has nothing to do with actions). No backfill
needed.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE change_request_versions ADD COLUMN IF NOT EXISTS proposed_action_link_id UUID"
    )
    op.execute(
        "ALTER TABLE change_request_versions DROP CONSTRAINT IF EXISTS change_request_versions_proposed_action_link_id_fkey"
    )
    op.execute(
        "ALTER TABLE change_request_versions ADD CONSTRAINT change_request_versions_proposed_action_link_id_fkey "
        "FOREIGN KEY (proposed_action_link_id) REFERENCES requirement_actions(id) ON DELETE SET NULL"
    )
    op.execute(
        "ALTER TABLE change_request_versions ADD COLUMN IF NOT EXISTS proposed_action_title VARCHAR(500)"
    )
    op.execute(
        "ALTER TABLE change_request_versions ADD COLUMN IF NOT EXISTS proposed_action_description TEXT"
    )
    op.execute(
        "ALTER TABLE change_request_versions ADD COLUMN IF NOT EXISTS proposed_action_type_id UUID"
    )
    op.execute(
        "ALTER TABLE change_request_versions DROP CONSTRAINT IF EXISTS change_request_versions_proposed_action_type_id_fkey"
    )
    op.execute(
        "ALTER TABLE change_request_versions ADD CONSTRAINT change_request_versions_proposed_action_type_id_fkey "
        "FOREIGN KEY (proposed_action_type_id) REFERENCES action_type_definitions(id) ON DELETE SET NULL"
    )
    op.execute(
        "ALTER TABLE change_request_versions ADD COLUMN IF NOT EXISTS proposed_action_assignee_id UUID"
    )
    op.execute(
        "ALTER TABLE change_request_versions DROP CONSTRAINT IF EXISTS change_request_versions_proposed_action_assignee_id_fkey"
    )
    op.execute(
        "ALTER TABLE change_request_versions ADD CONSTRAINT change_request_versions_proposed_action_assignee_id_fkey "
        "FOREIGN KEY (proposed_action_assignee_id) REFERENCES users(id)"
    )
    op.execute(
        "ALTER TABLE change_request_versions ADD COLUMN IF NOT EXISTS proposed_action_due_date DATE"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE change_request_versions DROP COLUMN IF EXISTS proposed_action_due_date")
    op.execute(
        "ALTER TABLE change_request_versions DROP CONSTRAINT IF EXISTS change_request_versions_proposed_action_assignee_id_fkey"
    )
    op.execute("ALTER TABLE change_request_versions DROP COLUMN IF EXISTS proposed_action_assignee_id")
    op.execute(
        "ALTER TABLE change_request_versions DROP CONSTRAINT IF EXISTS change_request_versions_proposed_action_type_id_fkey"
    )
    op.execute("ALTER TABLE change_request_versions DROP COLUMN IF EXISTS proposed_action_type_id")
    op.execute("ALTER TABLE change_request_versions DROP COLUMN IF EXISTS proposed_action_description")
    op.execute("ALTER TABLE change_request_versions DROP COLUMN IF EXISTS proposed_action_title")
    op.execute(
        "ALTER TABLE change_request_versions DROP CONSTRAINT IF EXISTS change_request_versions_proposed_action_link_id_fkey"
    )
    op.execute("ALTER TABLE change_request_versions DROP COLUMN IF EXISTS proposed_action_link_id")
