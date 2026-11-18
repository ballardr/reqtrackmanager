"""System Architecture domains

Revision ID: 0199
Revises: 0198
Create Date: 2026-11-17

Makes a domain (Software, Hardware, ...) a vocabulary row instead of one of three fixed values: `architecture_domains`
(owned by a project or an organisation, like the types) and one link table for each type vocabulary
(`architecture_element_type_domains`, `architecture_connection_type_domains`), so a type is in any number of domains.

Existing data is converted: an organisation that has a type (its own, or one in its projects) in `software` or `hardware`,
or a diagram toggle rule naming one, gets the Software and Hardware rows it uses; each such type is linked to the row; a
toggle rule's `domains` values become `domain_ids`; `any` becomes no link (a type with no domain fits every domain). The
`domain` column is then dropped. Nothing is created for an organisation that used neither, and a migration seeds no defaults.

The downgrade writes back the first linked domain named Software or Hardware (else `any`) and the matching rule values; a
custom domain is lost. Guarded so a database built from the current models (no `domain` column) passes.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0199"
down_revision: str | None = "0198"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TYPE_TABLES = (
    ("architecture_element_types", "architecture_element_type_domains", "element_type_id"),
    ("architecture_connection_types", "architecture_connection_type_domains", "connection_type_id"),
)


def _has_column(table: str, column: str) -> bool:
    """Whether `table` has `column` (a database built from the current models has no `domain`)."""
    return any(c["name"] == column for c in sa.inspect(op.get_bind()).get_columns(table))


def _create_tables() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS architecture_domains (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
            organization_id UUID REFERENCES organizations(id) ON DELETE CASCADE,
            name VARCHAR(100) NOT NULL,
            sort_order INTEGER NOT NULL DEFAULT 0,
            CONSTRAINT uq_architecture_domains_project_name UNIQUE (project_id, name),
            CONSTRAINT uq_architecture_domains_org_name UNIQUE (organization_id, name),
            CONSTRAINT ck_architecture_domains_one_owner CHECK ((project_id IS NULL) <> (organization_id IS NULL))
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_architecture_domains_project_id ON architecture_domains (project_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_architecture_domains_organization_id ON architecture_domains (organization_id)")
    for table, link, column in _TYPE_TABLES:
        op.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {link} (
                {column} UUID NOT NULL REFERENCES {table}(id) ON DELETE CASCADE,
                domain_id UUID NOT NULL REFERENCES architecture_domains(id) ON DELETE CASCADE,
                PRIMARY KEY ({column}, domain_id)
            )
            """
        )
        op.execute(f"CREATE INDEX IF NOT EXISTS ix_{link}_domain_id ON {link} (domain_id)")


def _convert_existing_data() -> None:
    """Creates the Software and Hardware rows an organisation used, links the types and rewrites the toggle rules."""
    used = []
    for table, _link, _column in _TYPE_TABLES:
        if _has_column(table, "domain"):
            used.append(
                f"SELECT COALESCE(t.organization_id, p.organization_id) AS org_id, t.domain AS dom FROM {table} t "
                "LEFT JOIN projects p ON p.id = t.project_id WHERE t.domain IN ('software', 'hardware')"
            )
    used.append(
        "SELECT p.organization_id AS org_id, d.value AS dom FROM architecture_diagram_toggles tg "
        "JOIN architecture_diagrams g ON g.id = tg.diagram_id JOIN projects p ON p.id = g.project_id "
        "CROSS JOIN LATERAL jsonb_array_elements_text("
        "CASE WHEN jsonb_typeof(tg.rule -> 'domains') = 'array' THEN tg.rule -> 'domains' ELSE CAST('[]' AS jsonb) END"
        ") AS d(value) WHERE d.value IN ('software', 'hardware')"
    )
    op.execute(
        f"""
        INSERT INTO architecture_domains (organization_id, name, sort_order)
        SELECT DISTINCT org_id, CASE dom WHEN 'software' THEN 'Software' ELSE 'Hardware' END,
               CASE dom WHEN 'software' THEN 0 ELSE 1 END
        FROM ({' UNION '.join(used)}) AS used
        ON CONFLICT (organization_id, name) DO NOTHING
        """
    )
    for table, link, column in _TYPE_TABLES:
        if not _has_column(table, "domain"):
            continue
        op.execute(
            f"""
            INSERT INTO {link} ({column}, domain_id)
            SELECT t.id, d.id FROM {table} t LEFT JOIN projects p ON p.id = t.project_id
            JOIN architecture_domains d
              ON d.organization_id = COALESCE(t.organization_id, p.organization_id) AND lower(d.name) = t.domain
            WHERE t.domain IN ('software', 'hardware')
            ON CONFLICT DO NOTHING
            """
        )
    op.execute(
        """
        UPDATE architecture_diagram_toggles tg
        SET rule = (tg.rule - 'domains') || COALESCE((
            SELECT jsonb_build_object('domain_ids', jsonb_agg(CAST(d.id AS text) ORDER BY d.sort_order))
            FROM architecture_diagrams g
            JOIN projects p ON p.id = g.project_id
            JOIN architecture_domains d ON d.organization_id = p.organization_id
            WHERE g.id = tg.diagram_id AND lower(d.name) IN (
                SELECT jsonb_array_elements_text(tg.rule -> 'domains')
            )
            HAVING count(*) > 0
        ), CAST('{}' AS jsonb))
        WHERE jsonb_typeof(tg.rule -> 'domains') = 'array'
        """
    )
    op.execute("UPDATE architecture_diagram_toggles SET rule = rule - 'domains' WHERE rule -> 'domains' IS NOT NULL")


def upgrade() -> None:
    _create_tables()
    _convert_existing_data()
    for table, _link, _column in _TYPE_TABLES:
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS domain")


def downgrade() -> None:
    for table, link, column in _TYPE_TABLES:
        op.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS domain VARCHAR(20) NOT NULL DEFAULT 'any'")
        op.execute(
            f"""
            UPDATE {table} t SET domain = first.dom
            FROM (
                SELECT DISTINCT ON (l.{column}) l.{column} AS type_id, lower(d.name) AS dom
                FROM {link} l JOIN architecture_domains d ON d.id = l.domain_id
                WHERE lower(d.name) IN ('software', 'hardware')
                ORDER BY l.{column}, d.sort_order, d.name
            ) AS first
            WHERE first.type_id = t.id
            """
        )
    op.execute(
        """
        UPDATE architecture_diagram_toggles tg
        SET rule = (tg.rule - 'domain_ids') || COALESCE((
            SELECT jsonb_build_object('domains', jsonb_agg(lower(d.name) ORDER BY d.sort_order))
            FROM architecture_domains d
            WHERE lower(d.name) IN ('software', 'hardware')
              AND CAST(d.id AS text) IN (SELECT jsonb_array_elements_text(tg.rule -> 'domain_ids'))
            HAVING count(*) > 0
        ), CAST('{}' AS jsonb))
        WHERE jsonb_typeof(tg.rule -> 'domain_ids') = 'array'
        """
    )
    op.execute("UPDATE architecture_diagram_toggles SET rule = rule - 'domain_ids' WHERE rule -> 'domain_ids' IS NOT NULL")
    op.execute("DELETE FROM project_definition_suppressions WHERE definition_kind = 'architecture_domain'")
    for _table, link, _column in _TYPE_TABLES:
        op.execute(f"DROP TABLE IF EXISTS {link}")
    op.execute("DROP TABLE IF EXISTS architecture_domains")
