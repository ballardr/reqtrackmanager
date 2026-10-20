"""Change request task assignees become principals

Revision ID: 0083
Revises: 0082
Create Date: 2026-10-13

`change_request_tasks.assignee_id` may now name a user, an organisation group
or a project group. It gets an
`assignee_type` column (existing rows backfill to `user`), the foreign key to
`users` is dropped (the id now points at one of three tables; the service
validates it), and a check constraint keeps the pair consistent.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0083"
down_revision: str | None = "0082"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TYPES = "'user', 'org_group', 'project_group'"


def upgrade() -> None:
    op.execute("ALTER TABLE change_request_tasks ADD COLUMN IF NOT EXISTS assignee_type VARCHAR(20)")
    op.execute(
        "UPDATE change_request_tasks SET assignee_type = 'user' WHERE assignee_type IS NULL AND assignee_id IS NOT NULL"
    )
    op.execute("ALTER TABLE change_request_tasks DROP CONSTRAINT IF EXISTS change_request_tasks_assignee_id_fkey")
    op.execute("ALTER TABLE change_request_tasks DROP CONSTRAINT IF EXISTS ck_assignee_principal")
    op.execute(
        f"ALTER TABLE change_request_tasks ADD CONSTRAINT ck_assignee_principal CHECK "
        f"((assignee_type IS NULL OR assignee_type IN ({_TYPES})) AND (assignee_type IS NULL) = (assignee_id IS NULL))"
    )


def downgrade() -> None:
    # Lossy: the type column goes, and the user foreign key is not restored because a task
    # assigned to a group has no user to point at.
    op.execute("ALTER TABLE change_request_tasks DROP CONSTRAINT IF EXISTS ck_assignee_principal")
    op.execute("ALTER TABLE change_request_tasks DROP COLUMN IF EXISTS assignee_type")
