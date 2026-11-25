"""Defer the foreign keys from compliance rows to org-level definition types

Revision ID: 0080
Revises: 0079
Create Date: 2026-10-12

Deleting an organisation cascades to its action types and relationship types and, through its standards, to the required
actions and mappings that reference them. Immediate `NO ACTION` foreign keys can be rejected by whichever cascade branch
runs first, so these two constraints are deferrable and initially deferred: they are checked at commit, after every
cascade branch, and an in-use type is still refused.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0080"
down_revision: str | None = "0079"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONSTRAINTS = (
    ("compliance_required_actions", "compliance_required_actions_action_type_id_fkey"),
    ("compliance_requirement_mappings", "compliance_requirement_mappings_relationship_type_id_fkey"),
)


def upgrade() -> None:
    for table, constraint in _CONSTRAINTS:
        op.execute(f"ALTER TABLE {table} ALTER CONSTRAINT {constraint} DEFERRABLE INITIALLY DEFERRED")


def downgrade() -> None:
    for table, constraint in _CONSTRAINTS:
        op.execute(f"ALTER TABLE {table} ALTER CONSTRAINT {constraint} NOT DEFERRABLE")
