"""Requirement owners and reviewers become principals (users and groups on parity, Phase 6c)

Revision ID: 0084
Revises: 0083
Create Date: 2026-10-13

`requirement_versions.owner_id` (mandatory), `requirement_versions.reviewer_id`
and `change_request_versions.proposed_reviewer_id` may now name a user, an
organisation group or a project group
(docs/plans/users-and-groups-parity-plan.md). Each gets a `*_type` column
(existing rows backfill to `user`; the owner's becomes NOT NULL), the foreign
key to `users` is dropped (the id now points at one of three tables; the
service validates it), and a check constraint keeps the pair consistent. Every
version row is backfilled, so history keeps who owned and reviewed each
version. `approval_authority_id` is untouched: it records the user who
approved, never an assignment.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0084"
down_revision: str | None = "0083"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TYPES = "'user', 'org_group', 'project_group'"

# (table, field base name, mandatory)
_FIELDS = (
    ("requirement_versions", "owner", True),
    ("requirement_versions", "reviewer", False),
    ("change_request_versions", "proposed_reviewer", False),
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
