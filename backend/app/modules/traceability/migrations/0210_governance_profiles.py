"""Governance profiles and their lifecycle, approval, review and baseline policy rows

Revision ID: 0210
Revises: 0209
Create Date: 2026-11-26

Organisation policy sets with their targets, exemptions and per-project choices, the policy tables a profile or a
project owns, and governance health's defaults, settings and snapshots. Nothing is seeded: with no profile every
project's governance is unchanged. Guarded so a database built from the current models passes.
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
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS governance_review_policies (
            id UUID PRIMARY KEY,
            profile_id UUID REFERENCES governance_profiles(id) ON DELETE CASCADE,
            project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
            artefact_type VARCHAR(64) NOT NULL,
            interval_days INTEGER,
            lead_days INTEGER,
            default_owner_type VARCHAR(20),
            default_owner_id UUID,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            CONSTRAINT ck_governance_review_policies_one_owner CHECK ((profile_id IS NULL) <> (project_id IS NULL)),
            CONSTRAINT ck_governance_review_policies_interval CHECK (interval_days IS NULL OR interval_days BETWEEN 1 AND 3650),
            CONSTRAINT ck_governance_review_policies_lead CHECK (lead_days IS NULL OR lead_days BETWEEN 0 AND 365),
            CONSTRAINT ck_default_owner_principal CHECK (
                (default_owner_type IS NULL OR default_owner_type IN ('user', 'org_group', 'project_group'))
                AND (default_owner_type IS NULL) = (default_owner_id IS NULL)
            ),
            CONSTRAINT uq_governance_review_policies_profile UNIQUE (profile_id, artefact_type),
            CONSTRAINT uq_governance_review_policies_project UNIQUE (project_id, artefact_type)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_governance_review_policies_profile_id ON governance_review_policies (profile_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_governance_review_policies_project_id ON governance_review_policies (project_id)")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS governance_baseline_policies (
            id UUID PRIMARY KEY,
            profile_id UUID REFERENCES governance_profiles(id) ON DELETE CASCADE,
            project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
            applies_to_stage BOOLEAN NOT NULL,
            applies_to_manual BOOLEAN NOT NULL,
            notify_managers BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            CONSTRAINT ck_governance_baseline_policies_one_owner CHECK ((profile_id IS NULL) <> (project_id IS NULL)),
            CONSTRAINT ck_governance_baseline_policies_applies CHECK (applies_to_stage OR applies_to_manual),
            CONSTRAINT uq_governance_baseline_policies_profile UNIQUE (profile_id),
            CONSTRAINT uq_governance_baseline_policies_project UNIQUE (project_id)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_governance_baseline_policies_profile_id ON governance_baseline_policies (profile_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_governance_baseline_policies_project_id ON governance_baseline_policies (project_id)")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS governance_baseline_checks (
            id UUID PRIMARY KEY,
            policy_id UUID NOT NULL REFERENCES governance_baseline_policies(id) ON DELETE CASCADE,
            check_key VARCHAR(200) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            CONSTRAINT uq_governance_baseline_checks UNIQUE (policy_id, check_key)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_governance_baseline_checks_policy_id ON governance_baseline_checks (policy_id)")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS governance_baseline_required_fields (
            id UUID PRIMARY KEY,
            policy_id UUID NOT NULL REFERENCES governance_baseline_policies(id) ON DELETE CASCADE,
            artefact_type VARCHAR(64) NOT NULL,
            field_key VARCHAR(100) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            CONSTRAINT uq_governance_baseline_required_fields UNIQUE (policy_id, artefact_type, field_key)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_governance_baseline_required_fields_policy_id "
        "ON governance_baseline_required_fields (policy_id)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS governance_health_defaults (
            id UUID PRIMARY KEY,
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            mode VARCHAR(24) NOT NULL,
            interval_hours INTEGER NOT NULL DEFAULT 24,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            CONSTRAINT uq_governance_health_defaults_org UNIQUE (organization_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_governance_health_defaults_organization_id ON governance_health_defaults (organization_id)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS governance_health_settings (
            id UUID PRIMARY KEY,
            project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            mode VARCHAR(24),
            interval_hours INTEGER,
            checks_runner_id UUID REFERENCES users(id) ON DELETE SET NULL,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            CONSTRAINT uq_governance_health_settings_project UNIQUE (project_id),
            CONSTRAINT ck_governance_health_settings_interval CHECK (interval_hours IS NULL OR interval_hours >= 1)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_governance_health_settings_project_id ON governance_health_settings (project_id)")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS governance_health_snapshots (
            id UUID PRIMARY KEY,
            project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            computed_at TIMESTAMPTZ NOT NULL,
            payload JSONB NOT NULL,
            refreshed_by_id UUID REFERENCES users(id) ON DELETE SET NULL,
            checks_run_by_id UUID REFERENCES users(id) ON DELETE SET NULL,
            checks_run_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            CONSTRAINT uq_governance_health_snapshots_project UNIQUE (project_id)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_governance_health_snapshots_project_id ON governance_health_snapshots (project_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS governance_health_snapshots")
    op.execute("DROP TABLE IF EXISTS governance_health_settings")
    op.execute("DROP TABLE IF EXISTS governance_health_defaults")
    op.execute("DROP TABLE IF EXISTS governance_baseline_required_fields")
    op.execute("DROP TABLE IF EXISTS governance_baseline_checks")
    op.execute("DROP TABLE IF EXISTS governance_baseline_policies")
    op.execute("DROP TABLE IF EXISTS governance_review_policies")
    op.execute("DROP TABLE IF EXISTS governance_approval_policy_roles")
    op.execute("DROP TABLE IF EXISTS governance_approval_policies")
    op.execute("DROP TABLE IF EXISTS governance_lifecycle_skip_policies")
    op.execute("DROP TABLE IF EXISTS governance_lifecycle_requirements")
    for table in ("governance_profile_choices", "governance_profile_exemptions", "governance_profile_targets"):
        op.execute(f"DROP TABLE IF EXISTS {table}")
    op.execute("DROP TABLE IF EXISTS governance_profiles")
