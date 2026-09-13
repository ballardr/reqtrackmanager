"""Compliance data model (compliance module Phase 5)

Revision ID: 0026
Revises: 0025
Create Date: 2026-09-05

Adds the five tables backing the Compliance Module's data model
(docs/Compliance_Module_Requirements.md §2, §5, §6, §25, §31;
docs/compliance-module-plan.md Phase 5) — the first real first-party module
built on the module system Phases 0-4 laid down before it:

- `compliance_standards` (`app.modules.compliance.models.
  ComplianceStandard`) — an organisation-level, reusable compliance
  standard definition.
- `compliance_standard_versions` (`ComplianceStandardVersion`) — versioned
  content per standard (§4); every version remains independently
  addressable indefinitely (no `valid_from`/`valid_to` supersession, unlike
  `requirement_versions` — see that model's own docstring for why).
- `compliance_requirements` (`ComplianceRequirement`) — self-referential
  (`parent_requirement_id`) for section/subsection hierarchy (§5).
- `compliance_required_actions` (`ComplianceRequiredAction`) — one-to-many
  from a requirement, not a link table (§6).
- `compliance_action_type_definitions` (`ComplianceActionTypeDefinition`)
  — organisation-scoped extensible action-type vocabulary, mirroring
  `action_type_definitions`' existing pattern at org rather than project
  scope.

All five tables start empty: this phase adds no seed data (Compliance's
"potential initial action types," §6, are seeded in Phase 15) and no
existing table is altered. `compliance_required_actions.action_type_id`
must be created after `compliance_action_type_definitions` (its FK target);
`compliance_requirements` must be created after
`compliance_standard_versions`, which must be created after
`compliance_standards` — the table order below follows those dependencies.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0026"
down_revision: str | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS compliance_action_type_definitions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            name VARCHAR(100) NOT NULL,
            sort_order INTEGER NOT NULL DEFAULT 0,
            UNIQUE (organization_id, name)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_compliance_action_type_definitions_organization_id "
        "ON compliance_action_type_definitions (organization_id)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS compliance_standards (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            reference VARCHAR(64) NOT NULL,
            name VARCHAR(255) NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            issuing_organisation VARCHAR(255),
            owner_id UUID NOT NULL REFERENCES users(id),
            creator_id UUID NOT NULL REFERENCES users(id),
            is_archived BOOLEAN NOT NULL DEFAULT false,
            archived_at TIMESTAMPTZ,
            archived_by UUID REFERENCES users(id),
            UNIQUE (organization_id, reference)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_compliance_standards_organization_id "
        "ON compliance_standards (organization_id)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS compliance_standard_versions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            standard_id UUID NOT NULL REFERENCES compliance_standards(id) ON DELETE CASCADE,
            version_number INTEGER NOT NULL,
            version_label VARCHAR(50) NOT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'draft',
            effective_date DATE,
            change_note TEXT NOT NULL DEFAULT '',
            created_by UUID NOT NULL REFERENCES users(id),
            published_at TIMESTAMPTZ,
            published_by UUID REFERENCES users(id),
            retired_at TIMESTAMPTZ,
            retired_by UUID REFERENCES users(id),
            UNIQUE (standard_id, version_number)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_compliance_standard_versions_standard_id "
        "ON compliance_standard_versions (standard_id)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS compliance_requirements (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            standard_version_id UUID NOT NULL REFERENCES compliance_standard_versions(id) ON DELETE CASCADE,
            parent_requirement_id UUID REFERENCES compliance_requirements(id) ON DELETE CASCADE,
            reference VARCHAR(64),
            name VARCHAR(500) NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            reasoning TEXT NOT NULL DEFAULT '',
            sort_order INTEGER NOT NULL DEFAULT 0,
            created_by UUID NOT NULL REFERENCES users(id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_compliance_requirements_standard_version_id "
        "ON compliance_requirements (standard_version_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_compliance_requirements_parent_requirement_id "
        "ON compliance_requirements (parent_requirement_id)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS compliance_required_actions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            requirement_id UUID NOT NULL REFERENCES compliance_requirements(id) ON DELETE CASCADE,
            action_type_id UUID NOT NULL REFERENCES compliance_action_type_definitions(id),
            name VARCHAR(500) NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            is_mandatory BOOLEAN NOT NULL DEFAULT true,
            sort_order INTEGER NOT NULL DEFAULT 0,
            created_by UUID NOT NULL REFERENCES users(id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_compliance_required_actions_requirement_id "
        "ON compliance_required_actions (requirement_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS compliance_required_actions")
    op.execute("DROP TABLE IF EXISTS compliance_requirements")
    op.execute("DROP TABLE IF EXISTS compliance_standard_versions")
    op.execute("DROP TABLE IF EXISTS compliance_standards")
    op.execute("DROP TABLE IF EXISTS compliance_action_type_definitions")
