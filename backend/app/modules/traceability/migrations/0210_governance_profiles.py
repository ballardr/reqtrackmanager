"""Governance profiles: organisation policy sets with their targets, exemptions, per-project choices and lifecycle policy

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


    op.execute(
        """
        CREATE TABLE IF NOT EXISTS governance_lifecycle_requirements (
            id UUID PRIMARY KEY,
            profile_id UUID NOT NULL REFERENCES governance_profiles(id) ON DELETE CASCADE,
            artefact_type VARCHAR(64) NOT NULL,
            state VARCHAR(64) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            CONSTRAINT uq_governance_lifecycle_requirements UNIQUE (profile_id, artefact_type, state)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_governance_lifecycle_requirements_profile_id "
        "ON governance_lifecycle_requirements (profile_id)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS governance_lifecycle_skip_policies (
            id UUID PRIMARY KEY,
            profile_id UUID NOT NULL REFERENCES governance_profiles(id) ON DELETE CASCADE,
            forbidden BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            CONSTRAINT uq_governance_lifecycle_skip_policies UNIQUE (profile_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_governance_lifecycle_skip_policies_profile_id "
        "ON governance_lifecycle_skip_policies (profile_id)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS governance_approval_policies (
            id UUID PRIMARY KEY,
            profile_id UUID REFERENCES governance_profiles(id) ON DELETE CASCADE,
            project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
            artefact_type VARCHAR(64) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            CONSTRAINT ck_governance_approval_policies_one_owner CHECK ((profile_id IS NULL) <> (project_id IS NULL)),
            CONSTRAINT uq_governance_approval_policies_profile UNIQUE (profile_id, artefact_type),
            CONSTRAINT uq_governance_approval_policies_project UNIQUE (project_id, artefact_type)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_governance_approval_policies_profile_id ON governance_approval_policies (profile_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_governance_approval_policies_project_id ON governance_approval_policies (project_id)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS governance_approval_policy_roles (
            id UUID PRIMARY KEY,
            policy_id UUID NOT NULL REFERENCES governance_approval_policies(id) ON DELETE CASCADE,
            role_kind VARCHAR(16) NOT NULL,
            role_key VARCHAR(200) NOT NULL,
            custom_role_id UUID REFERENCES custom_role_definitions(id) ON DELETE CASCADE,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            CONSTRAINT uq_governance_approval_policy_roles UNIQUE (policy_id, role_kind, role_key)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_governance_approval_policy_roles_policy_id ON governance_approval_policy_roles (policy_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_governance_approval_policy_roles_custom_role_id "
        "ON governance_approval_policy_roles (custom_role_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS governance_approval_policy_roles")
    op.execute("DROP TABLE IF EXISTS governance_approval_policies")
    op.execute("DROP TABLE IF EXISTS governance_lifecycle_skip_policies")
    op.execute("DROP TABLE IF EXISTS governance_lifecycle_requirements")
    for table in ("governance_profile_choices", "governance_profile_exemptions", "governance_profile_targets"):
        op.execute(f"DROP TABLE IF EXISTS {table}")
    op.execute("DROP TABLE IF EXISTS governance_profiles")
