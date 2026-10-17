"""Requirement action assignees become principals

Revision ID: 0082
Revises: 0081
Create Date: 2026-10-12

`requirement_actions.assignee_id` and
`change_request_versions.proposed_action_assignee_id` may now name a user, an
organisation group or a project group.
Each gets a `*_type` column
(existing rows backfill to `user`), the foreign key to `users` is dropped (the
id now points at one of three tables; the service validates it), and a check
constraint keeps the pair consistent. Every change request version row is
backfilled, so history keeps who each version proposed.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0082"
down_revision: str | None = "0081"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TYPES = "'user', 'org_group', 'project_group'"

# (table, field base name) pairs whose optional field becomes a principal.
_FIELDS = (
    ("requirement_actions", "assignee"),
    ("change_request_versions", "proposed_action_assignee"),
)


def upgrade() -> None:
    for table, field in _FIELDS:
        op.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {field}_type VARCHAR(20)")
        op.execute(f"UPDATE {table} SET {field}_type = 'user' WHERE {field}_type IS NULL AND {field}_id IS NOT NULL")
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {table}_{field}_id_fkey")
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS ck_{field}_principal")
        op.execute(
            f"ALTER TABLE {table} ADD CONSTRAINT ck_{field}_principal CHECK "
            f"(({field}_type IS NULL OR {field}_type IN ({_TYPES})) AND ({field}_type IS NULL) = ({field}_id IS NULL))"
        )


def downgrade() -> None:
    # Lossy: the type column goes, and the user foreign key is not restored because a row
    # assigned to a group has no user to point at.
    for table, field in _FIELDS:
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS ck_{field}_principal")
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS {field}_type")
