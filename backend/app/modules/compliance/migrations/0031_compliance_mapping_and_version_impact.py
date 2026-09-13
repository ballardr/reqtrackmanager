"""Compliance cross-standard mapping + version impact (compliance module Phase 11)

Revision ID: 0031
Revises: 0030
Create Date: 2026-09-06

Adds the schema backing the Compliance Module's Phase 11 (docs/Compliance_
Module_Requirements.md §19, §27; docs/compliance-module-plan.md Phase 11):

- `compliance_requirements.cloned_from_requirement_id` — a nullable,
  self-referential FK recording which requirement (in an earlier version of
  the same standard) a given requirement was cloned from, if any. Set by
  `app.modules.compliance.router._clone_requirement_tree` at clone time;
  consumed by `app.modules.compliance.service.diff_standard_versions` to
  distinguish an unchanged/modified requirement from a genuinely added one
  (§27). `ON DELETE SET NULL`, not `CASCADE` — see `models.py`'s own Phase
  11 design-decisions section for why this differs from `parent_
  requirement_id`'s own `CASCADE` one column up.
- `compliance_mapping_relationship_types` (`ComplianceMappingRelationshipType
  Definition`) — an organisation-scoped, extensible vocabulary of cross-
  standard-mapping relationship types (§19: "Equivalent," "Satisfies,"
  "Derived From," "Related To," "Overlaps," "Conflicts With" are named
  examples, not a fixed set), mirroring `compliance_action_type_definitions`'
  exact shape plus one extra column, `implies_equivalence` (boolean,
  default `false`) — whether this type is strong enough that a `replaced`
  version-diff pair linked by it may have its assessment carried forward
  during project migration, subject to a separate, explicit per-migration
  human confirmation (see `models.py`'s own Phase 11 notes). Named without
  the `..._type_definitions` suffix its own column names would otherwise
  suggest — see `models.py`'s own docstring for why (a shorter table name
  avoids a >63-byte auto-generated index name on `organization_id`).
- `compliance_requirement_mappings` (`ComplianceRequirementMapping`) — a
  directed relationship between two `ComplianceRequirement` rows (§19's
  cross-standard mapping; also reused, per `models.py`'s own notes, for
  §27's "replaced" version-diff category, a same-standard, cross-version
  link). Soft-deletable (`is_archived`/`archived_at`/`archived_by`),
  mirroring every other entity in this module.
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
