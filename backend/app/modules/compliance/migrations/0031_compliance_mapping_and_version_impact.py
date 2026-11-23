"""Compliance cross-standard mapping + version impact

Revision ID: 0031
Revises: 0030
Create Date: 2026-09-06

Adds the schema of cross-standard mapping and version impact (§19, §27):

- `compliance_requirements.cloned_from_requirement_id`: nullable self-referential FK to the requirement (in an earlier
  version of the same standard) this one was cloned from. Set by `router._clone_requirement_tree` and read by
  `service.diff_standard_versions` to tell an unchanged or modified requirement from an added one (§27). `ON DELETE SET
  NULL`, unlike `parent_requirement_id`'s `CASCADE` (see `models.py`).
- `compliance_mapping_relationship_types` (`ComplianceMappingRelationshipTypeDefinition`): an organisation-scoped,
  extensible vocabulary of mapping relationship types (§19: Equivalent, Satisfies, Derived From, Related To, Overlaps,
  Conflicts With are examples), shaped like `compliance_action_type_definitions` plus `implies_equivalence` (boolean,
  default `false`): whether a `replaced` version-diff pair linked by it may have its assessment carried forward during
  project migration, subject to explicit per-migration confirmation. The shorter table name keeps the auto-generated
  `organization_id` index name under 63 bytes.
- `compliance_requirement_mappings` (`ComplianceRequirementMapping`): a directed relationship between two
  `ComplianceRequirement` rows (§19), also used for §27's `replaced` category (a same-standard, cross-version link).
  Soft-deletable (`is_archived`, `archived_at`, `archived_by`).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0031"
down_revision: str | None = "0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE compliance_requirements ADD COLUMN IF NOT EXISTS cloned_from_requirement_id "
        "UUID REFERENCES compliance_requirements(id) ON DELETE SET NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_compliance_requirements_cloned_from_requirement_id "
        "ON compliance_requirements (cloned_from_requirement_id)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS compliance_mapping_relationship_types (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            name VARCHAR(100) NOT NULL,
            sort_order INTEGER NOT NULL DEFAULT 0,
            implies_equivalence BOOLEAN NOT NULL DEFAULT false,
            UNIQUE (organization_id, name)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_compliance_mapping_relationship_types_organization_id "
        "ON compliance_mapping_relationship_types (organization_id)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS compliance_requirement_mappings (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            from_requirement_id UUID NOT NULL REFERENCES compliance_requirements(id) ON DELETE CASCADE,
            to_requirement_id UUID NOT NULL REFERENCES compliance_requirements(id) ON DELETE CASCADE,
            relationship_type_id UUID NOT NULL REFERENCES compliance_mapping_relationship_types(id),
            notes TEXT NOT NULL DEFAULT '',
            created_by UUID NOT NULL REFERENCES users(id),
            is_archived BOOLEAN NOT NULL DEFAULT false,
            archived_at TIMESTAMPTZ,
            archived_by UUID REFERENCES users(id),
            CONSTRAINT ck_compliance_requirement_mappings_no_self_link
                CHECK (from_requirement_id != to_requirement_id),
            UNIQUE (from_requirement_id, to_requirement_id, relationship_type_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_compliance_requirement_mappings_organization_id "
        "ON compliance_requirement_mappings (organization_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_compliance_requirement_mappings_from_requirement_id "
        "ON compliance_requirement_mappings (from_requirement_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_compliance_requirement_mappings_to_requirement_id "
        "ON compliance_requirement_mappings (to_requirement_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS compliance_requirement_mappings")
    op.execute("DROP TABLE IF EXISTS compliance_mapping_relationship_types")
    op.execute(
        "ALTER TABLE compliance_requirements DROP COLUMN IF EXISTS cloned_from_requirement_id"
    )
