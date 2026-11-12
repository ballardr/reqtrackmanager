"""System Architecture symbol library: symbols, and the symbol columns on element types and elements

Revision ID: 0175
Revises: 0174
Create Date: 2026-11-12

Adds `architecture_symbols` (owned by a project or an organisation, a CHECK keeping exactly one; a stored file or a
built-in drawing, a CHECK keeping exactly one) and a nullable `symbol_id` on `architecture_element_types` and
`architecture_elements`.

Existing organisations get the built-in symbol rows backfilled (rows only: no file is stored, and no element type
is changed), since `on_org_created` only seeds organisations created afterwards. Guarded so a database built from
the current models passes.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0175"
down_revision: str | None = "0174"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (name, builtin_key)
_BUILTINS = (
    ("Device", "device"), ("Server", "server"), ("Database", "database"), ("Queue", "queue"), ("Firewall", "firewall"),
    ("Cloud", "cloud"), ("Sensor", "sensor"), ("Board", "board"), ("Connector", "connector"), ("User", "user"),
)


def _sql_text(value: str) -> str:
    """A single-quoted SQL literal (the values here are constants of this file)."""
    return "'" + value.replace("'", "''") + "'"


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS architecture_symbols (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
            organization_id UUID REFERENCES organizations(id) ON DELETE CASCADE,
            name VARCHAR(100) NOT NULL,
            file_asset_id UUID REFERENCES file_assets(id) ON DELETE SET NULL,
            builtin_key VARCHAR(40),
            sort_order INTEGER NOT NULL DEFAULT 0,
            CONSTRAINT uq_architecture_symbols_project_name UNIQUE (project_id, name),
            CONSTRAINT uq_architecture_symbols_org_name UNIQUE (organization_id, name),
            CONSTRAINT ck_architecture_symbols_one_owner CHECK ((project_id IS NULL) <> (organization_id IS NULL)),
            CONSTRAINT ck_architecture_symbols_one_source CHECK ((file_asset_id IS NULL) <> (builtin_key IS NULL))
        )
        """
    )
    for column in ("project_id", "organization_id", "file_asset_id"):
        op.execute(f"CREATE INDEX IF NOT EXISTS ix_architecture_symbols_{column} ON architecture_symbols ({column})")

    for table in ("architecture_element_types", "architecture_elements"):
        op.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS symbol_id UUID REFERENCES architecture_symbols(id) ON DELETE SET NULL")
        op.execute(f"CREATE INDEX IF NOT EXISTS ix_{table}_symbol_id ON {table} (symbol_id)")

    values = ", ".join(f"({i}, {_sql_text(name)}, {_sql_text(key)})" for i, (name, key) in enumerate(_BUILTINS))
    op.execute(
        f"""
        INSERT INTO architecture_symbols (organization_id, name, builtin_key, sort_order)
        SELECT o.id, v.name, v.builtin_key, v.sort_order
        FROM organizations o
        CROSS JOIN (VALUES {values}) AS v(sort_order, name, builtin_key)
        ON CONFLICT DO NOTHING
        """
    )


def downgrade() -> None:
    for table in ("architecture_elements", "architecture_element_types"):
        op.execute(f"DROP INDEX IF EXISTS ix_{table}_symbol_id")
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS symbol_id")
    op.execute("DROP TABLE IF EXISTS architecture_symbols")
