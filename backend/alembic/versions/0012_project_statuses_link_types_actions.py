"""Project statuses, typed bidirectional requirement links, and requirement actions

Revision ID: 0012
Revises: 0011
Create Date: 2026-08-17

Three additive features, one migration:

1. **Org-definable project statuses** (`project_status_definitions`):
   4 defaults (Proposed/Active/Abandoned/Completed) backfilled per existing
   organisation, then `projects.status_id` (new, NOT NULL, no `ON DELETE` —
   see `models/project_status.py`'s docstring for why) is backfilled to
   each project's own organisation's lowest-`sort_order` status ("Proposed").

2. **Typed, bidirectional, org-extensible requirement links**
   (`requirement_link_type_definitions`): 12 default forward/reverse name
   pairs backfilled per existing organisation, then
   `requirement_links.link_type_id` (new FK) replaces the old fixed
   `link_type` enum column entirely.

   The enum -> FK backfill (the tricky part): the old `link_type` column
   only ever held three values (`relates_to`, `depends_on`, `derived_from`
   — the retired `RequirementLinkType` enum). Each existing link row is
   matched to the new per-organisation `requirement_link_type_definitions`
   row whose `forward_name` is that value's plain-English equivalent
   ("Related to" / "Depends on" / "Derives from" respectively), resolved
   through the link's *source* requirement's project's organisation (a link
   is between two requirements in the same project, so either end's
   organisation would do; the source is used for consistency with the
   FK's own directionality). This UPDATE is guarded by an
   `information_schema.columns` existence check on the old `link_type`
   column: a brand-new database's `0001_initial.py` builds straight from
   the *current* models (see 0001's own docstring), which no longer have
   that column at all, so this whole block is a deliberate no-op there —
   only a database migrated before this revision ever has `link_type` to
   read from. The old 3-part unique constraint (on `link_type`) is located
   and dropped dynamically by inspecting `pg_constraint`/`pg_attribute`
   rather than by a literal `DROP CONSTRAINT <guessed-name>`, because
   Postgres silently truncates that constraint's default-generated name
   (over the 63-byte `NAMEDATALEN` limit) to something not worth trying to
   reproduce by hand.

3. **Requirement actions** (`action_type_definitions`, `requirement_actions`,
   `requirement_action_links`, `requirement_action_files`): 2 default
   action types (Review, Test) backfilled per existing *project* (not
   organisation — action types are project-scoped, see
   `models/action_type.py`'s docstring), plus `projects.next_action_seq`
   for `RequirementAction.unique_code` generation.

Every statement is `IF NOT EXISTS`/`IF EXISTS` (or an explicit
`pg_constraint`/`information_schema` existence check where plain
`IF NOT EXISTS` isn't available, e.g. `ALTER TABLE ... ADD CONSTRAINT`),
for the same reason every migration since 0002 uses that style: 0001's
`create_all()` already creates all of this against the *current* model
classes on a brand-new database, so a plain (non-guarded) DDL statement
here would fail there with "already exists"; an already-migrated database
from before this revision is genuinely missing it. Backfills are safe
unconditionally either way — a fresh database has no pre-existing rows to
backfill (no-op).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- 1. Project statuses ------------------------------------------------

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS project_status_definitions (
            id UUID PRIMARY KEY,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            name VARCHAR(100) NOT NULL,
            sort_order INTEGER NOT NULL DEFAULT 0,
            CONSTRAINT project_status_definitions_organization_id_name_key UNIQUE (organization_id, name)
        )
        """
    )
    op.execute(
        """
        INSERT INTO project_status_definitions (id, created_at, updated_at, organization_id, name, sort_order)
        SELECT gen_random_uuid(), now(), now(), o.id, v.name, v.sort_order
        FROM organizations o
        CROSS JOIN (VALUES ('Proposed', 0), ('Active', 1), ('Abandoned', 2), ('Completed', 3)) AS v(name, sort_order)
        WHERE NOT EXISTS (
            SELECT 1 FROM project_status_definitions psd
            WHERE psd.organization_id = o.id AND psd.name = v.name
        )
        """
    )

    op.execute("ALTER TABLE projects ADD COLUMN IF NOT EXISTS status_id UUID")
    op.execute(
        """
        UPDATE projects p
        SET status_id = (
            SELECT psd.id FROM project_status_definitions psd
            WHERE psd.organization_id = p.organization_id
            ORDER BY psd.sort_order ASC
            LIMIT 1
        )
        WHERE p.status_id IS NULL
        """
    )
    op.execute("ALTER TABLE projects ALTER COLUMN status_id SET NOT NULL")
    op.execute("ALTER TABLE projects DROP CONSTRAINT IF EXISTS projects_status_id_fkey")
    op.execute(
        "ALTER TABLE projects ADD CONSTRAINT projects_status_id_fkey "
        "FOREIGN KEY (status_id) REFERENCES project_status_definitions(id)"
    )

    # --- 2. Typed, bidirectional requirement link types ---------------------

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS requirement_link_type_definitions (
            id UUID PRIMARY KEY,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            forward_name VARCHAR(100) NOT NULL,
            reverse_name VARCHAR(100) NOT NULL,
            sort_order INTEGER NOT NULL DEFAULT 0,
            CONSTRAINT uq_requirement_link_type_definitions_org_forward UNIQUE (organization_id, forward_name)
        )
        """
    )
    op.execute(
        """
        INSERT INTO requirement_link_type_definitions
            (id, created_at, updated_at, organization_id, forward_name, reverse_name, sort_order)
        SELECT gen_random_uuid(), now(), now(), o.id, v.forward_name, v.reverse_name, v.sort_order
        FROM organizations o
        CROSS JOIN (VALUES
            ('Related to', 'Related to', 0),
            ('Derives from', 'Is the source of', 1),
            ('Satisfies', 'Is satisfied by', 2),
            ('Refines', 'Is refined by', 3),
            ('Depends on', 'Is a dependency of', 4),
            ('Conflicts with', 'Conflicts with', 5),
            ('Implements', 'Is implemented by', 6),
            ('Allocated to', 'Has allocated', 7),
            ('Verified by', 'Verifies', 8),
            ('Validated by', 'Validates', 9),
            ('Mitigates', 'Is mitigated by', 10),
            ('Equivalent to', 'Equivalent to', 11)
        ) AS v(forward_name, reverse_name, sort_order)
        WHERE NOT EXISTS (
            SELECT 1 FROM requirement_link_type_definitions rltd
            WHERE rltd.organization_id = o.id AND rltd.forward_name = v.forward_name
        )
        """
    )

    op.execute("ALTER TABLE requirement_links ADD COLUMN IF NOT EXISTS link_type_id UUID")
    # See this migration's module docstring for the full explanation of this
    # guarded backfill: only a pre-0012 database ever has the old
    # `link_type` column to read from.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'requirement_links' AND column_name = 'link_type'
            ) THEN
                UPDATE requirement_links rl
                SET link_type_id = (
                    SELECT rltd.id FROM requirement_link_type_definitions rltd
                    JOIN requirements r ON r.id = rl.source_requirement_id
                    JOIN projects p ON p.id = r.project_id
                    WHERE rltd.organization_id = p.organization_id
                      AND rltd.forward_name = CASE rl.link_type
                            WHEN 'relates_to' THEN 'Related to'
                            WHEN 'depends_on' THEN 'Depends on'
                            WHEN 'derived_from' THEN 'Derives from'
                          END
                    LIMIT 1
                )
                WHERE rl.link_type_id IS NULL;
            END IF;
        END $$;
        """
    )
    op.execute("ALTER TABLE requirement_links ALTER COLUMN link_type_id SET NOT NULL")
    op.execute("ALTER TABLE requirement_links DROP CONSTRAINT IF EXISTS requirement_links_link_type_id_fkey")
    op.execute(
        "ALTER TABLE requirement_links ADD CONSTRAINT requirement_links_link_type_id_fkey "
        "FOREIGN KEY (link_type_id) REFERENCES requirement_link_type_definitions(id)"
    )
    # Drop the old 3-part (..., link_type) unique constraint, whichever name
    # Postgres actually gave it (see module docstring — its default-generated
    # name is over NAMEDATALEN and gets silently truncated, so it's located
    # by column membership instead of a guessed literal name).
    op.execute(
        """
        DO $$
        DECLARE
            old_constraint RECORD;
        BEGIN
            FOR old_constraint IN
                SELECT con.conname
                FROM pg_constraint con
                JOIN pg_class rel ON rel.oid = con.conrelid
                WHERE rel.relname = 'requirement_links'
                  AND con.contype = 'u'
                  AND EXISTS (
                      SELECT 1 FROM unnest(con.conkey) AS colnum
                      JOIN pg_attribute att ON att.attrelid = con.conrelid AND att.attnum = colnum
                      WHERE att.attname = 'link_type'
                  )
            LOOP
                EXECUTE 'ALTER TABLE requirement_links DROP CONSTRAINT ' || quote_ident(old_constraint.conname);
            END LOOP;
        END $$;
        """
    )
    op.execute("ALTER TABLE requirement_links DROP COLUMN IF EXISTS link_type")
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_requirement_links_source_target_type') THEN
                ALTER TABLE requirement_links
                    ADD CONSTRAINT uq_requirement_links_source_target_type
                    UNIQUE (source_requirement_id, target_requirement_id, link_type_id);
            END IF;
        END $$;
        """
    )

    # --- 3. Requirement actions ----------------------------------------------

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS action_type_definitions (
            id UUID PRIMARY KEY,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            name VARCHAR(100) NOT NULL,
            sort_order INTEGER NOT NULL DEFAULT 0,
            CONSTRAINT action_type_definitions_project_id_name_key UNIQUE (project_id, name)
        )
        """
    )
    op.execute(
        """
        INSERT INTO action_type_definitions (id, created_at, updated_at, project_id, name, sort_order)
        SELECT gen_random_uuid(), now(), now(), pr.id, v.name, v.sort_order
        FROM projects pr
        CROSS JOIN (VALUES ('Review', 0), ('Test', 1)) AS v(name, sort_order)
        WHERE NOT EXISTS (
            SELECT 1 FROM action_type_definitions atd
            WHERE atd.project_id = pr.id AND atd.name = v.name
        )
        """
    )

    op.execute("ALTER TABLE projects ADD COLUMN IF NOT EXISTS next_action_seq INTEGER NOT NULL DEFAULT 1")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS requirement_actions (
            id UUID PRIMARY KEY,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            unique_code VARCHAR(64) NOT NULL,
            action_type_id UUID NOT NULL REFERENCES action_type_definitions(id),
            title VARCHAR(500) NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            outcome_status VARCHAR(20) NOT NULL DEFAULT 'pending',
            assignee_id UUID REFERENCES users(id),
            due_date DATE,
            completed_at TIMESTAMPTZ,
            completed_by UUID REFERENCES users(id),
            creator_id UUID NOT NULL REFERENCES users(id),
            is_archived BOOLEAN NOT NULL DEFAULT false,
            archived_at TIMESTAMPTZ,
            archived_by UUID REFERENCES users(id),
            CONSTRAINT requirement_actions_project_id_unique_code_key UNIQUE (project_id, unique_code)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_requirement_actions_unique_code ON requirement_actions (unique_code)")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS requirement_action_links (
            id UUID PRIMARY KEY,
            requirement_id UUID NOT NULL REFERENCES requirements(id) ON DELETE CASCADE,
            action_id UUID NOT NULL REFERENCES requirement_actions(id) ON DELETE CASCADE,
            linked_by UUID NOT NULL REFERENCES users(id),
            created_at TIMESTAMPTZ NOT NULL,
            CONSTRAINT requirement_action_links_requirement_id_action_id_key UNIQUE (requirement_id, action_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_requirement_action_links_requirement_id "
        "ON requirement_action_links (requirement_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_requirement_action_links_action_id ON requirement_action_links (action_id)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS requirement_action_files (
            id UUID PRIMARY KEY,
            action_id UUID NOT NULL REFERENCES requirement_actions(id) ON DELETE CASCADE,
            file_id UUID NOT NULL REFERENCES file_assets(id) ON DELETE CASCADE,
            linked_by UUID NOT NULL REFERENCES users(id),
            created_at TIMESTAMPTZ NOT NULL,
            CONSTRAINT requirement_action_files_action_id_file_id_key UNIQUE (action_id, file_id)
        )
        """
    )
    # No extra index on action_id here: mirrors `RequirementFile`, which has
    # no index on its own `requirement_id` either — see
    # `RequirementActionFile`'s model docstring ("exact shape of
    # RequirementFile").

    # No migration needed for ReviewTargetType.ACTION itself: `str_enum`
    # columns are plain VARCHAR (see 0004's note on adding "optional" to
    # RequirementLevel for the same reasoning), and no existing
    # `review_comments`/`comment_files` row can already reference it.


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS requirement_action_files")
    op.execute("DROP TABLE IF EXISTS requirement_action_links")
    op.execute("DROP TABLE IF EXISTS requirement_actions")
    op.execute("ALTER TABLE projects DROP COLUMN IF EXISTS next_action_seq")
    op.execute("DROP TABLE IF EXISTS action_type_definitions")

    op.execute("ALTER TABLE requirement_links ADD COLUMN IF NOT EXISTS link_type VARCHAR(30)")
    op.execute(
        """
        UPDATE requirement_links rl
        SET link_type = CASE rltd.forward_name
            WHEN 'Related to' THEN 'relates_to'
            WHEN 'Depends on' THEN 'depends_on'
            WHEN 'Derives from' THEN 'derived_from'
            ELSE 'relates_to'
        END
        FROM requirement_link_type_definitions rltd
        WHERE rltd.id = rl.link_type_id
        """
    )
    op.execute("ALTER TABLE requirement_links ALTER COLUMN link_type SET NOT NULL")
    op.execute("ALTER TABLE requirement_links DROP CONSTRAINT IF EXISTS uq_requirement_links_source_target_type")
    op.execute("ALTER TABLE requirement_links DROP CONSTRAINT IF EXISTS requirement_links_link_type_id_fkey")
    op.execute("ALTER TABLE requirement_links DROP COLUMN IF EXISTS link_type_id")
    # Restore a 3-part unique constraint on (source, target, link_type),
    # letting Postgres pick its own default name rather than trying to
    # reproduce the original pre-0012 name exactly (which was itself over
    # NAMEDATALEN and silently truncated — see this migration's module
    # docstring) — located dynamically so repeated downgrade/upgrade cycles
    # stay idempotent instead of erroring on a duplicate.
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint con
                JOIN pg_class rel ON rel.oid = con.conrelid
                WHERE rel.relname = 'requirement_links'
                  AND con.contype = 'u'
                  AND EXISTS (
                      SELECT 1 FROM unnest(con.conkey) AS colnum
                      JOIN pg_attribute att ON att.attrelid = con.conrelid AND att.attnum = colnum
                      WHERE att.attname = 'link_type'
                  )
            ) THEN
                ALTER TABLE requirement_links
                    ADD UNIQUE (source_requirement_id, target_requirement_id, link_type);
            END IF;
        END $$;
        """
    )
    op.execute("DROP TABLE IF EXISTS requirement_link_type_definitions")

    op.execute("ALTER TABLE projects DROP CONSTRAINT IF EXISTS projects_status_id_fkey")
    op.execute("ALTER TABLE projects DROP COLUMN IF EXISTS status_id")
    op.execute("DROP TABLE IF EXISTS project_status_definitions")
