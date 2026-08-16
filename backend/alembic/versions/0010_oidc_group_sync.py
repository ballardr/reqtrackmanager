"""OIDC org-group sync

Revision ID: 0010
Revises: 0009
Create Date: 2026-08-16

Adds `org_groups.idp_synced_group_name` — when set, marks an `OrgGroup`'s
*user* membership as fully managed by `services/oidc_provisioning.py`'s
`sync_org_groups_from_claims`, matched against the IdP's groups/roles claim
on every login (see that function's docstring). Unique per organisation via
a partial index (Postgres supports `CREATE UNIQUE INDEX IF NOT EXISTS`,
unlike `ADD CONSTRAINT`, so no `pg_constraint` check-and-branch is needed
here the way 0009's constraint renames needed one).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE org_groups ADD COLUMN IF NOT EXISTS idp_synced_group_name VARCHAR(255)")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_org_group_idp_synced_group_name "
        "ON org_groups (organization_id, idp_synced_group_name) WHERE idp_synced_group_name IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_org_group_idp_synced_group_name")
    op.execute("ALTER TABLE org_groups DROP COLUMN IF EXISTS idp_synced_group_name")
