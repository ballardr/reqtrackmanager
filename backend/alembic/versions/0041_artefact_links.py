"""Generic polymorphic relationship model (Module 0 — Platform Foundations, Phase 1)

Revision ID: 0041
Revises: 0040
Create Date: 2026-09-21

Per the Phase 0 decision record (docs/decisions.md, "Module 0 (Platform
Foundations) Phase 0"): builds the generic `artefact_links` table
(`app.models.relationship.ArtefactLink`) and folds both `requirement_links`
(`RequirementLink` — typed, requirement-to-requirement traceability) and
`requirement_action_links` (`RequirementActionLink` — untyped
action-to-requirement membership) into it, then drops both old tables.

**Column mapping** (see `ArtefactLink`'s own docstring for the full design):

- `requirement_links` row -> `source_type='requirement'`,
  `source_id=source_requirement_id`, `target_type='requirement'`,
  `target_id=target_requirement_id`, `link_type_id` preserved (always
  non-null on the old table), `created_by`/`created_at`/`updated_at`
  preserved.
- `requirement_action_links` row -> `source_type='requirement_action'`,
  `source_id=action_id`, `target_type='requirement'`,
  `target_id=requirement_id`, `link_type_id=NULL` (this table never had a
  type), `created_by=linked_by`, `created_at` preserved, `updated_at=
  created_at` (this table had no separate `updated_at` column).

**Row ids are preserved across the backfill** (`INSERT ... SELECT id, ...`,
not a fresh `gen_random_uuid()`) — this is required, not cosmetic:
`change_request_versions.proposed_link_id` holds a live FK reference to a
`requirement_links.id` value for any REMOVE_LINK change request still
pending decision at migration time, and that FK is repointed at
`artefact_links(id)` below rather than dropped. Preserving ids is what
keeps every such in-flight reference valid across the migration with no
separate remapping step. `requirement_action_links.id` has no external FK
referencing it (confirmed by a full-codebase grep before writing this
migration), so preserving its id isn't strictly required, but is done
anyway for consistency and because it's free.

**Duplicate prevention**: `artefact_links` has two constraints instead of
one 5-column unique constraint, because Postgres treats multiple `NULL`s in
a unique constraint as distinct from one another — a single constraint
including nullable `link_type_id` would silently stop preventing duplicate
*untyped* (action) links, a real regression from `requirement_action_links`'
old `UniqueConstraint(requirement_id, action_id)`. See `uq_artefact_links_typed`
(the non-null/typed case) and `ux_artefact_links_untyped` (a partial unique
index for the null/untyped case) below.

Every identifier here is kept within Postgres's 63-byte NAMEDATALEN limit
by explicit short names (this codebase has hit that limit before on wide
multi-column constraints — see migration 0009's own comment and
`RequirementLinkTypeDefinition.__table_args__`'s docstring for the
established precedent this follows).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0041"
down_revision: str | None = "0040"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- 1. Create the new generic table -------------------------------

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS artefact_links (
            id UUID PRIMARY KEY,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            source_type VARCHAR(20) NOT NULL,
            source_id UUID NOT NULL,
            target_type VARCHAR(20) NOT NULL,
            target_id UUID NOT NULL,
            link_type_id UUID REFERENCES requirement_link_type_definitions(id),
            created_by UUID NOT NULL REFERENCES users(id)
        )
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_artefact_links_typed') THEN
                ALTER TABLE artefact_links
                    ADD CONSTRAINT uq_artefact_links_typed
                    UNIQUE (source_type, source_id, target_type, target_id, link_type_id);
            END IF;
        END $$;
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_artefact_links_untyped ON artefact_links "
        "(source_type, source_id, target_type, target_id) WHERE link_type_id IS NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_artefact_links_target ON artefact_links (target_type, target_id)"
    )

    # --- 2. Backfill from requirement_links (typed, requirement<->requirement) ---

    op.execute(
        """
        INSERT INTO artefact_links
            (id, created_at, updated_at, source_type, source_id, target_type, target_id, link_type_id, created_by)
        SELECT
            rl.id, rl.created_at, rl.updated_at, 'requirement', rl.source_requirement_id,
            'requirement', rl.target_requirement_id, rl.link_type_id, rl.created_by
        FROM requirement_links rl
        WHERE NOT EXISTS (SELECT 1 FROM artefact_links al WHERE al.id = rl.id)
        """
    )

    # --- 3. Backfill from requirement_action_links (untyped, action<->requirement) ---

    op.execute(
        """
        INSERT INTO artefact_links
            (id, created_at, updated_at, source_type, source_id, target_type, target_id, link_type_id, created_by)
        SELECT
            ral.id, ral.created_at, ral.created_at, 'requirement_action', ral.action_id,
            'requirement', ral.requirement_id, NULL, ral.linked_by
        FROM requirement_action_links ral
        WHERE NOT EXISTS (SELECT 1 FROM artefact_links al WHERE al.id = ral.id)
        """
    )

    # --- 4. Repoint change_request_versions.proposed_link_id at the new table ---
    #
    # Row ids were preserved above, so every existing proposed_link_id value
    # (for any REMOVE_LINK change request still pending decision) remains
    # valid against artefact_links with no remapping needed — only the FK's
    # target table changes.

    op.execute(
        "ALTER TABLE change_request_versions DROP CONSTRAINT IF EXISTS change_request_versions_proposed_link_id_fkey"
    )
    op.execute(
        "ALTER TABLE change_request_versions ADD CONSTRAINT change_request_versions_proposed_link_id_fkey "
        "FOREIGN KEY (proposed_link_id) REFERENCES artefact_links(id) ON DELETE SET NULL"
    )

    # --- 5. Drop the old tables ------------------------------------------

    op.execute("DROP TABLE IF EXISTS requirement_links")
    op.execute("DROP TABLE IF EXISTS requirement_action_links")


def downgrade() -> None:
    # Recreate both old tables in their final pre-drop shape.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS requirement_links (
            id UUID PRIMARY KEY,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            source_requirement_id UUID NOT NULL REFERENCES requirements(id) ON DELETE CASCADE,
            target_requirement_id UUID NOT NULL REFERENCES requirements(id) ON DELETE CASCADE,
            link_type_id UUID NOT NULL REFERENCES requirement_link_type_definitions(id),
            created_by UUID NOT NULL REFERENCES users(id),
            CONSTRAINT uq_requirement_links_source_target_type
                UNIQUE (source_requirement_id, target_requirement_id, link_type_id)
        )
        """
    )
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

    # Repoint proposed_link_id back at requirement_links before artefact_links
    # is dropped.
    op.execute(
        "ALTER TABLE change_request_versions DROP CONSTRAINT IF EXISTS change_request_versions_proposed_link_id_fkey"
    )

    # Reverse-backfill, preserving ids (see upgrade()'s own docstring note).
    op.execute(
        """
        INSERT INTO requirement_links
            (id, created_at, updated_at, source_requirement_id, target_requirement_id, link_type_id, created_by)
        SELECT al.id, al.created_at, al.updated_at, al.source_id, al.target_id, al.link_type_id, al.created_by
        FROM artefact_links al
        WHERE al.source_type = 'requirement' AND al.target_type = 'requirement' AND al.link_type_id IS NOT NULL
        """
    )
    op.execute(
        """
        INSERT INTO requirement_action_links (id, requirement_id, action_id, linked_by, created_at)
        SELECT al.id, al.target_id, al.source_id, al.created_by, al.created_at
        FROM artefact_links al
        WHERE al.source_type = 'requirement_action' AND al.target_type = 'requirement' AND al.link_type_id IS NULL
        """
    )

    op.execute(
        "ALTER TABLE change_request_versions ADD CONSTRAINT change_request_versions_proposed_link_id_fkey "
        "FOREIGN KEY (proposed_link_id) REFERENCES requirement_links(id) ON DELETE SET NULL"
    )

    op.execute("DROP TABLE IF EXISTS artefact_links")
