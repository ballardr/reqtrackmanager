"""System Architecture records: elements, ports and connections

Revision ID: 0173
Revises: 0172
Create Date: 2026-11-12

Adds `architecture_elements` (a tree through `parent_id`, with an optional principal owner and an
optimistic `version`), `architecture_ports` (a child list of an element) and
`architecture_connections` (an interface between two elements). Guarded with IF NOT EXISTS so a
database built from the current models passes.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0173"
down_revision: str | None = "0172"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS architecture_elements (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            unique_code VARCHAR(64) NOT NULL,
            name VARCHAR(200) NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            element_type_id UUID NOT NULL REFERENCES architecture_element_types(id),
            parent_id UUID REFERENCES architecture_elements(id) ON DELETE SET NULL,
            owner_type VARCHAR(20),
            owner_id UUID,
            status VARCHAR(20) NOT NULL DEFAULT 'draft',
            version INTEGER NOT NULL DEFAULT 1,
            creator_id UUID NOT NULL REFERENCES users(id),
            is_archived BOOLEAN NOT NULL DEFAULT false,
            archived_at TIMESTAMPTZ,
            archived_by UUID REFERENCES users(id),
            CONSTRAINT uq_architecture_elements_project_unique_code UNIQUE (project_id, unique_code),
            CONSTRAINT ck_architecture_elements_not_own_parent CHECK (parent_id IS NULL OR parent_id <> id),
            CONSTRAINT ck_owner_principal CHECK (
                (owner_type IS NULL OR owner_type IN ('user', 'org_group', 'project_group'))
                AND ((owner_type IS NULL) = (owner_id IS NULL))
            )
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_architecture_elements_project_id ON architecture_elements (project_id)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_architecture_elements_element_type_id ON architecture_elements (element_type_id)"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_architecture_elements_parent_id ON architecture_elements (parent_id)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_architecture_elements_project_parent ON architecture_elements (project_id, parent_id)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS architecture_ports (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            element_id UUID NOT NULL REFERENCES architecture_elements(id) ON DELETE CASCADE,
            name VARCHAR(100) NOT NULL,
            direction VARCHAR(10) NOT NULL DEFAULT 'both',
            connection_type_id UUID REFERENCES architecture_connection_types(id) ON DELETE SET NULL,
            sort_order INTEGER NOT NULL DEFAULT 0,
            CONSTRAINT uq_architecture_ports_element_name UNIQUE (element_id, name)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_architecture_ports_element_id ON architecture_ports (element_id)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_architecture_ports_connection_type_id ON architecture_ports (connection_type_id)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS architecture_connections (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            unique_code VARCHAR(64) NOT NULL,
            name VARCHAR(200) NOT NULL DEFAULT '',
            connection_type_id UUID NOT NULL REFERENCES architecture_connection_types(id),
            source_element_id UUID NOT NULL REFERENCES architecture_elements(id),
            source_port_id UUID REFERENCES architecture_ports(id) ON DELETE SET NULL,
            target_element_id UUID NOT NULL REFERENCES architecture_elements(id),
            target_port_id UUID REFERENCES architecture_ports(id) ON DELETE SET NULL,
            protocol VARCHAR(200) NOT NULL DEFAULT '',
            description TEXT NOT NULL DEFAULT '',
            status VARCHAR(20) NOT NULL DEFAULT 'draft',
            version INTEGER NOT NULL DEFAULT 1,
            creator_id UUID NOT NULL REFERENCES users(id),
            is_archived BOOLEAN NOT NULL DEFAULT false,
            archived_at TIMESTAMPTZ,
            archived_by UUID REFERENCES users(id),
            CONSTRAINT uq_architecture_connections_project_unique_code UNIQUE (project_id, unique_code),
            CONSTRAINT ck_architecture_connections_distinct_ends CHECK (source_element_id <> target_element_id)
        )
        """
    )
    for column in ("project_id", "connection_type_id", "source_element_id", "target_element_id"):
        op.execute(
            f"CREATE INDEX IF NOT EXISTS ix_architecture_connections_{column} ON architecture_connections ({column})"
        )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS architecture_connections")
    op.execute("DROP TABLE IF EXISTS architecture_ports")
    op.execute("DROP TABLE IF EXISTS architecture_elements")
