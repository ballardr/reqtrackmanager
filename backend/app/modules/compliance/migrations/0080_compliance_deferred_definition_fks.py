"""Defer the foreign keys from compliance rows to org-level definition types

Revision ID: 0080
Revises: 0079
Create Date: 2026-10-12

Deleting an organisation cascades to its action types and relationship types and, through its
standards, to the required actions and mappings that reference them. The foreign keys were
immediate `NO ACTION`, so whichever cascade branch Postgres ran first could be rejected
("update or delete on table compliance_action_type_definitions violates foreign key constraint"),
and an organisation with a standard that had a required action could not be deleted. Making the
two constraints deferrable and initially deferred checks them at commit, after every cascade
branch has run; an in-use type is still refused.
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
