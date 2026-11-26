"""Requirement types: the organisation list, a project's view of it, and the type on a requirement version

Revision ID: 0212
Revises: 0211
Create Date: 2026-11-26

`requirement_type_definitions` (the organisation's ordered list) and `project_requirement_types` (a project's overrides
and own entries), a nullable `project_type_id` on `requirement_versions` and a nullable `proposed_project_type_id` on
`change_request_versions`. Each type has a nullable `rank` (priority, lower is higher; a project's null follows the
organisation's). Every existing organisation is given the default list, ranked 1 to 3; no requirement is typed. Guarded so a
database built from the current models passes.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0212"
down_revision: str | None = "0211"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DEFAULTS = ("Business Requirement", "Stakeholder Requirement", "Project Requirement")  # ranked 1, 2, 3


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS requirement_type_definitions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            name VARCHAR(100) NOT NULL,
            sort_order INTEGER NOT NULL DEFAULT 0,
            is_active BOOLEAN NOT NULL DEFAULT true,
            rank INTEGER,
            CONSTRAINT uq_requirement_type_definitions_org_name UNIQUE (organization_id, name)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS project_requirement_types (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            org_type_id UUID REFERENCES requirement_type_definitions(id) ON DELETE SET NULL,
            name_override VARCHAR(100),
            display_order_override INTEGER,
            is_enabled BOOLEAN NOT NULL DEFAULT true,
            rank INTEGER,
            CONSTRAINT uq_project_requirement_types_project_org_type UNIQUE (project_id, org_type_id),
            CONSTRAINT ck_project_requirement_types_local_has_name CHECK (org_type_id IS NOT NULL OR name_override IS NOT NULL)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_project_requirement_types_project_id ON project_requirement_types (project_id)")
    op.execute(
        "ALTER TABLE requirement_versions ADD COLUMN IF NOT EXISTS project_type_id UUID "
        "REFERENCES project_requirement_types(id) ON DELETE SET NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_requirement_versions_project_type_id ON requirement_versions (project_type_id)"
    )
    op.execute(
        "ALTER TABLE change_request_versions ADD COLUMN IF NOT EXISTS proposed_project_type_id UUID "
        "REFERENCES project_requirement_types(id) ON DELETE SET NULL"
    )
    for order, name in enumerate(_DEFAULTS):
        op.execute(
            "INSERT INTO requirement_type_definitions (organization_id, name, sort_order, rank) "
            f"SELECT id, '{name}', {order}, {order + 1} FROM organizations ON CONFLICT (organization_id, name) DO NOTHING"
        )


def downgrade() -> None:
    op.execute("ALTER TABLE change_request_versions DROP COLUMN IF EXISTS proposed_project_type_id")
    op.execute("DROP INDEX IF EXISTS ix_requirement_versions_project_type_id")
    op.execute("ALTER TABLE requirement_versions DROP COLUMN IF EXISTS project_type_id")
    op.execute("DROP TABLE IF EXISTS project_requirement_types")
    op.execute("DROP TABLE IF EXISTS requirement_type_definitions")
