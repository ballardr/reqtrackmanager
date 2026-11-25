"""Governance profiles: organisation policy sets with their targets, exemptions and per-project choices

Revision ID: 0210
Revises: 0209
Create Date: 2026-11-26

Nothing is seeded: with no profile every project's governance is unchanged. Guarded so a database built from the current
models passes.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0210"
down_revision: str | None = "0209"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS governance_profiles (
            id UUID PRIMARY KEY,
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            name VARCHAR(200) NOT NULL,
            description VARCHAR(500) NOT NULL DEFAULT '',
            mode VARCHAR(16) NOT NULL,
            target_kind VARCHAR(24) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            CONSTRAINT uq_governance_profiles_org_name UNIQUE (organization_id, name)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_governance_profiles_organization_id ON governance_profiles (organization_id)")
    for table, extra, unique in (
        ("governance_profile_targets", "include_children BOOLEAN NOT NULL DEFAULT FALSE", "uq_governance_profile_targets"),
        (
            "governance_profile_exemptions",
            "include_children BOOLEAN NOT NULL DEFAULT FALSE, reason VARCHAR(500) NOT NULL DEFAULT ''",
            "uq_governance_profile_exemptions",
        ),
        ("governance_profile_choices", "opted_in BOOLEAN NOT NULL", "uq_governance_profile_choices"),
    ):
        op.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {table} (
                id UUID PRIMARY KEY,
                profile_id UUID NOT NULL REFERENCES governance_profiles(id) ON DELETE CASCADE,
                project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                {extra},
                created_at TIMESTAMPTZ NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL,
                CONSTRAINT {unique} UNIQUE (profile_id, project_id)
            )
            """
        )
        op.execute(f"CREATE INDEX IF NOT EXISTS ix_{table}_profile_id ON {table} (profile_id)")
        op.execute(f"CREATE INDEX IF NOT EXISTS ix_{table}_project_id ON {table} (project_id)")


def downgrade() -> None:
    for table in ("governance_profile_choices", "governance_profile_exemptions", "governance_profile_targets"):
        op.execute(f"DROP TABLE IF EXISTS {table}")
    op.execute("DROP TABLE IF EXISTS governance_profiles")
