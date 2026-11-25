"""Add-action change request kind

Revision ID: 0013
Revises: 0012
Create Date: 2026-08-25

Gates action creation and linking on an APPROVED/COMPLETED requirement behind a change request, as a
requirement's own fields are (`services.requirements.LOCKED_STATUSES`). Adds an `ADD_ACTION`
`ChangeRequestKind` (a plain VARCHAR `str_enum` column, so the value needs no migration, as for
`ReviewTargetType.ACTION` in 0012) and six nullable columns on `change_request_versions` for the
proposed action: either `proposed_action_link_id` (link an existing `RequirementAction`) or
`proposed_action_title` + `proposed_action_type_id` (create one), mutually exclusive (see
`routers/change_requests.py::create_change_request`). Existing rows stay `NULL`; no backfill.
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
