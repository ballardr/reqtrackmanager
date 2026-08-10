"""Mandatory requirement target, optional description, CR field-level
change tracking, and comment attachments

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-10

- `requirement_versions.target_stage_id` becomes NOT NULL (backfilled from
  each requirement's own project's earliest stage, by `sort_order`, for any
  row that doesn't already have one — every project has at least one stage
  from creation, see `routers/projects.py::create_project`, so this always
  has something to backfill to).
- `requirement_versions.description`: new optional free-text field.
- `RequirementLevel` gains an `"optional"` member — no migration needed for
  the column itself (`str_enum` stores these as plain VARCHAR, see
  `models/base.py::str_enum`'s docstring for why).
- `change_request_versions.changed_fields` (JSONB list of field-name
  strings): the explicit record of which fields a change request actually
  proposes to change — see `docs/decisions.md`'s "Change request field-level
  tracking" entry for the full reasoning. `proposed_description` and
  `proposed_attachment_file_ids` are the two new proposed-content columns
  this feature needs alongside it.
- `comment_files`: new join table so a `ReviewComment` (the discussion
  thread shared by requirements and change requests) can carry file
  attachments.

`IF NOT EXISTS`/`IF EXISTS` for the new columns/table, same reason 0002/0003
use it: 0001's `create_all()` already creates these against the *current*
model classes on a brand-new database, so a plain `ADD COLUMN`/`CREATE
TABLE` would fail there with "already exists"; an already-migrated database
from before this revision is genuinely missing them. The `target_stage_id`
backfill+NOT NULL is safe unconditionally either way: a fresh database has
no rows to backfill (no-op), and `SET NOT NULL` on an already-not-null
column is a no-op in Postgres too.
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
    # The FK's ON DELETE action must change from SET NULL to CASCADE now
    # that the column is NOT NULL — SET NULL against a NOT NULL column
    # raises exactly the IntegrityError this migration is trying to
    # prevent, the moment a ProjectStage is ever removed via its parent
    # project/organisation being deleted (there's no standalone "delete a
    # stage" endpoint — see RequirementVersion.target_stage_id's model
    # docstring for why CASCADE is correct and safe here). Postgres has no
    # in-place "ALTER CONSTRAINT ... ON DELETE" — drop and recreate.
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
