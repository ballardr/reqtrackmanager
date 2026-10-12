"""Compliance standard owner, review owner and required-action assignee become principals (users and groups on parity, Phase 5)

Revision ID: 0079
Revises: 0078
Create Date: 2026-10-12

`compliance_standards.owner_id` (mandatory), `compliance_reviews.owner_id` and
`compliance_required_action_assessments.assignee_id` may now name a user, an
organisation group or (where the record is project-scoped) a project group
(docs/plans/users-and-groups-parity-plan.md). Each gets a `<name>_type` column
(existing rows backfill to `user`), the foreign key to `users` is dropped (the id
now points at one of three tables; the service validates it), and a check
constraint keeps the pair consistent.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0079"
down_revision: str | None = "0078"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TYPES = "'user', 'org_group', 'project_group'"

# (table, field, mandatory)
_FIELDS = (
    ("compliance_standards", "owner", True),
    ("compliance_reviews", "owner", False),
    ("compliance_required_action_assessments", "assignee", False),
)


def upgrade() -> None:
    for table, field, mandatory in _FIELDS:
        op.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {field}_type VARCHAR(20)")
        op.execute(f"UPDATE {table} SET {field}_type = 'user' WHERE {field}_type IS NULL AND {field}_id IS NOT NULL")
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {table}_{field}_id_fkey")
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS ck_{field}_principal")
        if mandatory:
            op.execute(f"ALTER TABLE {table} ALTER COLUMN {field}_type SET NOT NULL")
            check = f"{field}_type IN ({_TYPES})"
        else:
            check = (
                f"({field}_type IS NULL OR {field}_type IN ({_TYPES})) "
                f"AND ({field}_type IS NULL) = ({field}_id IS NULL)"
            )
        op.execute(f"ALTER TABLE {table} ADD CONSTRAINT ck_{field}_principal CHECK ({check})")


def downgrade() -> None:
    # Lossy: the type columns go, and the user foreign keys are not restored because a row
    # owned by a group has no user to point at.
    for table, field, _mandatory in _FIELDS:
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS ck_{field}_principal")
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS {field}_type")
