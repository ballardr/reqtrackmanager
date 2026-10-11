"""Link-type artefact restrictions, dedicated flag, and artefact-type link rules

Revision ID: 0066
Revises: 0065
Create Date: 2026-10-06

Adds `requirement_link_type_definitions.allowed_source_types` /
`allowed_target_types` (nullable JSONB lists; NULL = any artefact type) and
`dedicated_endpoint`, and the `artefact_type_link_rules` /
`artefact_type_link_rule_entries` tables (which link types an artefact type may
use). Existing link types stay unrestricted; only the "Supersedes" types, whose
links flip a status through their own action, are flagged dedicated.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0066"
down_revision: str | None = "0065"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Adds the restriction columns, the dedicated flag and the rule tables."""
    op.execute(
        "ALTER TABLE requirement_link_type_definitions "
        "ADD COLUMN IF NOT EXISTS allowed_source_types JSONB, "
        "ADD COLUMN IF NOT EXISTS allowed_target_types JSONB, "
        "ADD COLUMN IF NOT EXISTS dedicated_endpoint BOOLEAN NOT NULL DEFAULT false"
    )
    op.execute("UPDATE requirement_link_type_definitions SET dedicated_endpoint = true WHERE forward_name = 'Supersedes'")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS artefact_type_link_rules (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            artefact_type VARCHAR(40) NOT NULL,
            CONSTRAINT uq_artefact_type_link_rules_org_type UNIQUE (organization_id, artefact_type)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS artefact_type_link_rule_entries (
            rule_id UUID NOT NULL REFERENCES artefact_type_link_rules(id) ON DELETE CASCADE,
            link_type_id UUID NOT NULL REFERENCES requirement_link_type_definitions(id),
            PRIMARY KEY (rule_id, link_type_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_artefact_type_link_rule_entries_link_type "
        "ON artefact_type_link_rule_entries (link_type_id)"
    )


def downgrade() -> None:
    """Drops the rule tables and the added columns."""
    op.execute("DROP TABLE IF EXISTS artefact_type_link_rule_entries")
    op.execute("DROP TABLE IF EXISTS artefact_type_link_rules")
    op.execute(
        "ALTER TABLE requirement_link_type_definitions DROP COLUMN IF EXISTS dedicated_endpoint, "
        "DROP COLUMN IF EXISTS allowed_target_types, DROP COLUMN IF EXISTS allowed_source_types"
    )
