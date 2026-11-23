"""Persona, Stakeholder and Need owner/champion become principals

Revision ID: 0077
Revises: 0076
Create Date: 2026-10-12

Owner and champion columns may name a user or a group: adds `<name>_type`
(backfilled to `user` on every version), drops the user foreign keys and adds
a pair check. `stakeholder_versions.user_id` stays a user.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0077"
down_revision: str | None = "0076"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TYPES = "'user', 'org_group', 'project_group'"

# (table, field) pairs; every field is optional.
_FIELDS = (
    ("persona_versions", "owner"),
    ("persona_versions", "champion"),
    ("stakeholder_versions", "owner"),
    ("stakeholder_need_versions", "owner"),
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
    # Lossy: the type columns go, and the user foreign keys are not restored because a row
    # owned by a group has no user to point at.
    for table, field in _FIELDS:
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS ck_{field}_principal")
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS {field}_type")
