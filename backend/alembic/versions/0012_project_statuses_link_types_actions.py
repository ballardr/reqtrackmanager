"""Project statuses, typed bidirectional requirement links, and requirement actions

Revision ID: 0012
Revises: 0011
Create Date: 2026-08-17

Three additive features:

1. Org-definable project statuses (`project_status_definitions`): four defaults
   (Proposed/Active/Abandoned/Completed) per organisation; `projects.status_id` (NOT NULL, no
   `ON DELETE`; see `models/project_status.py`) is backfilled to the organisation's lowest-`sort_order`
   status.

2. Typed, bidirectional, org-extensible requirement links (`requirement_link_type_definitions`): twelve
   default forward/reverse name pairs per organisation; `requirement_links.link_type_id` (FK) replaces
   the `link_type` enum column. The backfill maps the three enum values (`relates_to`, `depends_on`,
   `derived_from`) to the organisation's "Related to" / "Depends on" / "Derives from" definitions,
   through the source requirement's project. It is guarded by an `information_schema.columns` check on
   the old column, which a database built from the current models does not have. The old 3-part unique
   constraint is found through `pg_constraint`/`pg_attribute` because Postgres truncates its generated
   name at the 63-byte `NAMEDATALEN` limit.

3. Requirement actions (`action_type_definitions`, `requirement_actions`, `requirement_action_links`,
   `requirement_action_files`): two default action types (Review, Test) per project (action types are
   project-scoped; see `models/action_type.py`), and `projects.next_action_seq` for
   `RequirementAction.unique_code`.

Statements are `IF NOT EXISTS`/`IF EXISTS`, or an explicit `pg_constraint`/`information_schema` check
where that is unavailable (`ALTER TABLE ... ADD CONSTRAINT`), as in 0002. Backfills are no-ops on a
database with no rows.
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

    # `RequirementLink` is replaced by the generic `ArtefactLink` table (migration 0041), so 0001's
    # `create_all()` no longer creates `requirement_links`. This guard creates the table in its
    # pre-0012 shape (including the fixed `link_type` column) so the statements below have a table to
    # operate on in a fresh chain. It is a no-op (IF NOT EXISTS) on an already-migrated database.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS requirement_links (
            id UUID PRIMARY KEY,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            source_requirement_id UUID NOT NULL REFERENCES requirements(id) ON DELETE CASCADE,
            target_requirement_id UUID NOT NULL REFERENCES requirements(id) ON DELETE CASCADE,
            link_type VARCHAR(30) NOT NULL,
            created_by UUID NOT NULL REFERENCES users(id)
        )
        """
    )

    op.execute("ALTER TABLE requirement_links ADD COLUMN IF NOT EXISTS link_type_id UUID")
    # Guarded backfill; see the module docstring. Only a database with the old `link_type` column has
    # values to read.
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
    # Drop the old 3-part (..., link_type) unique constraint by column membership: its generated name
    # was truncated at NAMEDATALEN.
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
    # No index on action_id, mirroring `RequirementFile` (see `RequirementActionFile`'s model docstring).

    # No migration for ReviewTargetType.ACTION: `str_enum` columns are plain VARCHAR (see 0004) and no
    # existing `review_comments`/`comment_files` row can reference it.


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
    # Restore a 3-part unique constraint on (source, target, link_type) under a Postgres-generated name,
    # found dynamically so repeated downgrade/upgrade cycles stay idempotent.
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
