"""System Architecture vocabularies: element types and connection types

Revision ID: 0172
Revises: 0171
Create Date: 2026-11-12

Adds `architecture_element_types` and `architecture_connection_types`. Each row is
owned by a project or by an organisation (a CHECK keeps exactly one).

Existing organisations get the default types backfilled, since `on_org_created`
only seeds organisations created afterwards; the module itself stays off until an
organisation enables it. Guarded so a database built from the current models passes.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0172"
down_revision: str | None = "0171"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COLORS = {
    "software": ("#2563EB", "#60A5FA"),
    "hardware": ("#B45309", "#FBBF24"),
    "any": ("#475569", "#94A3B8"),
}
# (name, shape, domain)
_ELEMENT_TYPES = (
    ("System", "rounded", "any"), ("Subsystem", "rounded", "any"), ("Component", "rectangle", "any"),
    ("Service", "hexagon", "software"), ("Container", "rectangle", "software"), ("Package", "folder", "software"),
    ("Datastore", "cylinder", "software"), ("Queue", "parallelogram", "software"), ("Board", "chip", "hardware"),
    ("Sensor", "ellipse", "hardware"), ("Connector", "hexagon", "hardware"), ("Enclosure", "rectangle", "hardware"),
)
# (name, domain, directional)
_CONNECTION_TYPES = (
    ("REST API", "software", True), ("gRPC", "software", True), ("Message queue", "software", True),
    ("Event stream", "software", True), ("Database access", "software", True), ("File exchange", "software", True),
    ("SPI", "hardware", False), ("I2C", "hardware", False), ("UART", "hardware", False), ("CAN", "hardware", False),
    ("Ethernet", "any", False), ("USB", "hardware", False), ("Power", "hardware", True),
    ("Analogue signal", "hardware", True),
)


def _create_table(table: str, extra_columns: str, check_name: str) -> None:
    """Creates one vocabulary table with its owner columns, constraints and indexes."""
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {table} (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
            organization_id UUID REFERENCES organizations(id) ON DELETE CASCADE,
            name VARCHAR(100) NOT NULL,
            domain VARCHAR(20) NOT NULL DEFAULT 'any',
            color_light VARCHAR(7),
            color_dark VARCHAR(7),
            sort_order INTEGER NOT NULL DEFAULT 0,
            {extra_columns},
            CONSTRAINT uq_{table}_project_name UNIQUE (project_id, name),
            CONSTRAINT uq_{table}_org_name UNIQUE (organization_id, name),
            CONSTRAINT {check_name} CHECK ((project_id IS NULL) <> (organization_id IS NULL))
        )
        """
    )
    op.execute(f"CREATE INDEX IF NOT EXISTS ix_{table}_project_id ON {table} (project_id)")
    op.execute(f"CREATE INDEX IF NOT EXISTS ix_{table}_organization_id ON {table} (organization_id)")


def _sql_text(value: str) -> str:
    """A single-quoted SQL literal (the values here are constants of this file)."""
    return "'" + value.replace("'", "''") + "'"


def upgrade() -> None:
    _create_table(
        "architecture_element_types", "shape VARCHAR(20) NOT NULL DEFAULT 'rectangle'",
        "ck_architecture_element_types_one_owner",
    )
    _create_table(
        "architecture_connection_types",
        "line_style VARCHAR(20) NOT NULL DEFAULT 'solid', directional BOOLEAN NOT NULL DEFAULT true",
        "ck_architecture_connection_types_one_owner",
    )

    element_values = ", ".join(
        f"({i}, {_sql_text(name)}, {_sql_text(shape)}, {_sql_text(domain)}, "
        f"{_sql_text(_COLORS[domain][0])}, {_sql_text(_COLORS[domain][1])})"
        for i, (name, shape, domain) in enumerate(_ELEMENT_TYPES)
    )
    op.execute(
        f"""
        INSERT INTO architecture_element_types (organization_id, name, shape, domain, color_light, color_dark, sort_order)
        SELECT o.id, v.name, v.shape, v.domain, v.light, v.dark, v.sort_order
        FROM organizations o
        CROSS JOIN (VALUES {element_values}) AS v(sort_order, name, shape, domain, light, dark)
        ON CONFLICT DO NOTHING
        """
    )
    connection_values = ", ".join(
        f"({i}, {_sql_text(name)}, {_sql_text(domain)}, {'true' if directional else 'false'}, "
        f"{_sql_text(_COLORS[domain][0])}, {_sql_text(_COLORS[domain][1])})"
        for i, (name, domain, directional) in enumerate(_CONNECTION_TYPES)
    )
    op.execute(
        f"""
        INSERT INTO architecture_connection_types
            (organization_id, name, domain, directional, line_style, color_light, color_dark, sort_order)
        SELECT o.id, v.name, v.domain, v.directional, 'solid', v.light, v.dark, v.sort_order
        FROM organizations o
        CROSS JOIN (VALUES {connection_values}) AS v(sort_order, name, domain, directional, light, dark)
        ON CONFLICT DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS architecture_connection_types")
    op.execute("DROP TABLE IF EXISTS architecture_element_types")
