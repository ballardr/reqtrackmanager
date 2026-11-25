"""Per-report-type report content

Revision ID: 0071
Revises: 0070
Create Date: 2026-10-11

Adds `report_contents`: the introduction, chapters and appendices a report template, project or
organisation holds for one report type (`models/report_content.py`). The requirements-report-only
columns move into `report_key = 'requirements'` rows and are dropped, leaving one store:

- `report_templates.intro / chapters / appendices`
- `projects.report_intro / report_chapters / report_appendices`
- `organizations.default_report_intro / default_report_chapters / default_report_appendices`

Only non-empty content is copied (an empty value meant "inherit", now the absence of a row). Each step
checks that the old column exists, because a database built from the current models by 0001 has neither
the old columns nor anything to copy.

The downgrade restores the columns from each scope's `requirements` row; other report types and the
"all reports" row are dropped with the table.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0071"
down_revision: str | None = "0070"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_column(table: str, column: str) -> bool:
    if not sa.inspect(op.get_bind()).has_table(table):
        return False
    return any(c["name"] == column for c in sa.inspect(op.get_bind()).get_columns(table))


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS report_contents (
            id UUID PRIMARY KEY,
            scope_type VARCHAR(20) NOT NULL,
            scope_id UUID NOT NULL,
            report_key VARCHAR(100) NOT NULL,
            intro TEXT NOT NULL DEFAULT '',
            chapters JSONB NOT NULL DEFAULT '[]'::jsonb,
            appendices JSONB NOT NULL DEFAULT '[]'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_report_contents_scope_key UNIQUE (scope_type, scope_id, report_key)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_report_contents_scope_id ON report_contents (scope_id)")

    if _has_column("report_templates", "intro"):
        op.execute(
            """
            INSERT INTO report_contents (id, scope_type, scope_id, report_key, intro, chapters, appendices)
            SELECT gen_random_uuid(), 'template', id, 'requirements', COALESCE(intro, ''),
                   COALESCE(chapters, '[]'::jsonb), COALESCE(appendices, '[]'::jsonb)
            FROM report_templates
            WHERE COALESCE(intro, '') <> '' OR jsonb_array_length(COALESCE(chapters, '[]'::jsonb)) > 0
               OR jsonb_array_length(COALESCE(appendices, '[]'::jsonb)) > 0
            ON CONFLICT DO NOTHING
            """
        )
        op.execute("ALTER TABLE report_templates DROP COLUMN intro, DROP COLUMN chapters, DROP COLUMN appendices")

    if _has_column("projects", "report_intro"):
        op.execute(
            """
            INSERT INTO report_contents (id, scope_type, scope_id, report_key, intro, chapters, appendices)
            SELECT gen_random_uuid(), 'project', id, 'requirements', COALESCE(report_intro, ''),
                   COALESCE(report_chapters, '[]'::jsonb), COALESCE(report_appendices, '[]'::jsonb)
            FROM projects
            WHERE COALESCE(report_intro, '') <> '' OR jsonb_array_length(COALESCE(report_chapters, '[]'::jsonb)) > 0
               OR jsonb_array_length(COALESCE(report_appendices, '[]'::jsonb)) > 0
            ON CONFLICT DO NOTHING
            """
        )
        op.execute(
            "ALTER TABLE projects DROP COLUMN report_intro, DROP COLUMN report_chapters, DROP COLUMN report_appendices"
        )

    if _has_column("organizations", "default_report_intro"):
        op.execute(
            """
            INSERT INTO report_contents (id, scope_type, scope_id, report_key, intro, chapters, appendices)
            SELECT gen_random_uuid(), 'organization', id, 'requirements', COALESCE(default_report_intro, ''),
                   COALESCE(default_report_chapters, '[]'::jsonb), COALESCE(default_report_appendices, '[]'::jsonb)
            FROM organizations
            WHERE COALESCE(default_report_intro, '') <> ''
               OR jsonb_array_length(COALESCE(default_report_chapters, '[]'::jsonb)) > 0
               OR jsonb_array_length(COALESCE(default_report_appendices, '[]'::jsonb)) > 0
            ON CONFLICT DO NOTHING
            """
        )
        op.execute(
            "ALTER TABLE organizations DROP COLUMN default_report_intro, DROP COLUMN default_report_chapters, "
            "DROP COLUMN default_report_appendices"
        )


def downgrade() -> None:
    op.execute("ALTER TABLE report_templates ADD COLUMN IF NOT EXISTS intro TEXT NOT NULL DEFAULT ''")
    op.execute("ALTER TABLE report_templates ADD COLUMN IF NOT EXISTS chapters JSONB NOT NULL DEFAULT '[]'::jsonb")
    op.execute("ALTER TABLE report_templates ADD COLUMN IF NOT EXISTS appendices JSONB NOT NULL DEFAULT '[]'::jsonb")
    op.execute("ALTER TABLE projects ADD COLUMN IF NOT EXISTS report_intro TEXT NOT NULL DEFAULT ''")
    op.execute("ALTER TABLE projects ADD COLUMN IF NOT EXISTS report_chapters JSONB NOT NULL DEFAULT '[]'::jsonb")
    op.execute("ALTER TABLE projects ADD COLUMN IF NOT EXISTS report_appendices JSONB NOT NULL DEFAULT '[]'::jsonb")
    op.execute("ALTER TABLE organizations ADD COLUMN IF NOT EXISTS default_report_intro TEXT")
    op.execute("ALTER TABLE organizations ADD COLUMN IF NOT EXISTS default_report_chapters JSONB")
    op.execute("ALTER TABLE organizations ADD COLUMN IF NOT EXISTS default_report_appendices JSONB")
    op.execute(
        """
        UPDATE report_templates t SET intro = c.intro, chapters = c.chapters, appendices = c.appendices
        FROM report_contents c
        WHERE c.scope_type = 'template' AND c.scope_id = t.id AND c.report_key = 'requirements'
        """
    )
    op.execute(
        """
        UPDATE projects p SET report_intro = c.intro, report_chapters = c.chapters, report_appendices = c.appendices
        FROM report_contents c
        WHERE c.scope_type = 'project' AND c.scope_id = p.id AND c.report_key = 'requirements'
        """
    )
    op.execute(
        """
        UPDATE organizations o SET default_report_intro = NULLIF(c.intro, ''),
            default_report_chapters = NULLIF(c.chapters, '[]'::jsonb),
            default_report_appendices = NULLIF(c.appendices, '[]'::jsonb)
        FROM report_contents c
        WHERE c.scope_type = 'organization' AND c.scope_id = o.id AND c.report_key = 'requirements'
        """
    )
    op.execute("DROP TABLE IF EXISTS report_contents")
