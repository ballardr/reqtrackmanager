"""Mandatory requirement target, optional description, CR field-level
change tracking, and comment attachments

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-10

- `requirement_versions.target_stage_id` becomes NOT NULL, backfilled from the project's earliest stage
  by `sort_order` (every project has a stage from creation; see `routers/projects.py::create_project`).
- `requirement_versions.description`: new optional free-text field.
- `RequirementLevel` gains an `"optional"` member; the column needs no migration because `str_enum`
  stores plain VARCHAR (see `models/base.py::str_enum`).
- `change_request_versions.changed_fields` (JSONB list of field names) records which fields a change
  request proposes to change (docs/decisions.md, "Change request field-level tracking");
  `proposed_description` and `proposed_attachment_file_ids` are the matching proposed-content columns.
- `comment_files`: join table so a `ReviewComment` can carry file attachments.

`IF NOT EXISTS`/`IF EXISTS` for the new columns and table, as in 0002. The `target_stage_id` backfill
and NOT NULL are idempotent: a fresh database has no rows to backfill and `SET NOT NULL` on a NOT NULL
column is a no-op.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE requirement_versions rv
        SET target_stage_id = (
            SELECT ps.id FROM project_stages ps
            JOIN requirements r ON r.project_id = ps.project_id
            WHERE r.id = rv.requirement_id
            ORDER BY ps.sort_order ASC
            LIMIT 1
        )
        WHERE rv.target_stage_id IS NULL
        """
    )
    op.execute("ALTER TABLE requirement_versions ALTER COLUMN target_stage_id SET NOT NULL")
    # The FK's ON DELETE action changes from SET NULL to CASCADE: SET NULL on a NOT NULL column raises an
    # IntegrityError when a parent project or organisation deletion removes a ProjectStage (see
    # RequirementVersion.target_stage_id). Postgres cannot alter the action in place, so the constraint is
    # dropped and recreated.
    op.execute("ALTER TABLE requirement_versions DROP CONSTRAINT IF EXISTS requirement_versions_target_stage_id_fkey")
    op.execute(
        "ALTER TABLE requirement_versions ADD CONSTRAINT requirement_versions_target_stage_id_fkey "
        "FOREIGN KEY (target_stage_id) REFERENCES project_stages(id) ON DELETE CASCADE"
    )
    op.execute("ALTER TABLE requirement_versions ADD COLUMN IF NOT EXISTS description TEXT NOT NULL DEFAULT ''")

    op.execute(
        "ALTER TABLE change_request_versions ADD COLUMN IF NOT EXISTS changed_fields JSONB NOT NULL DEFAULT '[]'::jsonb"
    )
    op.execute("ALTER TABLE change_request_versions ADD COLUMN IF NOT EXISTS proposed_description TEXT")
    op.execute(
        "ALTER TABLE change_request_versions ADD COLUMN IF NOT EXISTS proposed_attachment_file_ids "
        "JSONB NOT NULL DEFAULT '[]'::jsonb"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS comment_files (
            id UUID PRIMARY KEY,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            comment_id UUID NOT NULL REFERENCES review_comments(id) ON DELETE CASCADE,
            file_id UUID NOT NULL REFERENCES file_assets(id) ON DELETE CASCADE,
            uploaded_by UUID NOT NULL REFERENCES users(id)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_comment_files_comment_id ON comment_files (comment_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS comment_files")
    op.execute("ALTER TABLE change_request_versions DROP COLUMN IF EXISTS proposed_attachment_file_ids")
    op.execute("ALTER TABLE change_request_versions DROP COLUMN IF EXISTS proposed_description")
    op.execute("ALTER TABLE change_request_versions DROP COLUMN IF EXISTS changed_fields")
    op.execute("ALTER TABLE requirement_versions DROP COLUMN IF EXISTS description")
    op.execute("ALTER TABLE requirement_versions DROP CONSTRAINT IF EXISTS requirement_versions_target_stage_id_fkey")
    op.execute(
        "ALTER TABLE requirement_versions ADD CONSTRAINT requirement_versions_target_stage_id_fkey "
        "FOREIGN KEY (target_stage_id) REFERENCES project_stages(id) ON DELETE SET NULL"
    )
    op.execute("ALTER TABLE requirement_versions ALTER COLUMN target_stage_id DROP NOT NULL")
