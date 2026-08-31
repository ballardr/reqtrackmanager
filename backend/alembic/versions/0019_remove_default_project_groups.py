"""Remove default project groups; migrate to direct role grants

Revision ID: 0019
Revises: 0018
Create Date: 2026-08-31

Follow-up UX batch, Phase C (docs/decisions.md): `create_project`'s
non-template path used to auto-create four "standard" `ProjectGroup` rows
per project (`is_default=True` — "Project Managers"/"Project
Administrators"/"Stakeholders"/"Members", `DEFAULT_GROUPS` in
`routers/projects.py`) and grant the creator's initial `PROJECT_MANAGER`
role by adding them to the manager-role one. Those four groups could never
be deleted (`delete_project_group` special-cased `is_default`) and existed
on every project whether wanted or not, even though a direct
`UserProjectRole` grant — always the simpler, equally-supported mechanism
for a single person — was available the whole time. `create_project` now
grants the creator's initial manager role directly instead (see that
router's own updated docstring), and `is_default` is removed from the
schema entirely: no group is specially protected from deletion any more,
only the pre-existing "a project must always retain at least one manager"
(C-U-08) guard is.

This migration converts every *existing* `is_default=True` group's
membership into the new shape, so no existing project's manager-of-record
(or any other role granted via a default group) is silently lost:

For every `project_groups` row with `is_default = true`:
  1. Every direct user member (`project_group_members.user_id IS NOT
     NULL`) is materialized into a direct `user_project_roles` grant with
     the group's own `role`, idempotently (`ON CONFLICT ... DO NOTHING`
     against the existing `(user_id, project_id, role)` unique
     constraint — a user who already independently held the same direct
     role is left with exactly one row, not a duplicate).
  2. If the group has *only* plain direct user members — no nested org-
     group refs (`org_group_id`) and no cross-project member-source refs
     (`source_project_id`) — the now-fully-materialized group is deleted;
     `project_group_members` rows go with it via the existing `ON DELETE
     CASCADE` foreign key.
  3. If the group has any composition beyond plain direct members (found
     in real seed data: `seed_demo_data.py` attaches a `source_project_id`
     reference to the default "Stakeholders" group), it is *not* deleted —
     deleting it would silently drop that nested composition, which has no
     equivalent in a `UserProjectRole` row. Instead `is_default` is simply
     flipped to `false`: the group survives as an ordinary, fully-
     manageable custom group with its nested composition intact, on top of
     its direct members now also holding the same role directly (a
     harmless, redundant-but-not-wrong grant, same shape a real admin
     manually assigning both would produce).

C-U-08 ("every project must retain at least one manager") is preserved
exactly by construction here: every direct user member of a manager-role
default group ends up holding that same role directly, and the group
itself is only ever deleted (never just silently emptied) once every one
of its direct members has been carried forward — a group with a nested
org-group or cross-project reference contributing a manager is kept
around, unchanged in its own resolution, rather than deleted and losing
that contribution. See `backend/tests/test_default_group_migration.py`
for a pinning test exercising both branches (plain-default-group
materialize-then-delete, and has-extra-composition materialize-then-
demote) directly against this migration's own conversion logic.

Guarded by `IF EXISTS (... information_schema.columns ...)` the same way
0014/0017/0018 guard their own backfills: a brand-new database's
`0001_initial.py` already runs `Base.metadata.create_all()` against the
*current* model classes, which no longer define `is_default` at all, so a
fresh database never has the column to begin with and this whole backfill
is a no-op there — only a database migrated from before this revision has
real `is_default=True` rows to convert.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        DECLARE
            grp RECORD;
            has_extra_composition BOOLEAN;
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'project_groups' AND column_name = 'is_default'
            ) THEN
                FOR grp IN SELECT id, project_id, role FROM project_groups WHERE is_default = true
                LOOP
                    -- Materialize every direct user member into a direct
                    -- grant first, regardless of which branch this group
                    -- ends up taking below.
                    INSERT INTO user_project_roles (id, user_id, project_id, role, created_at, updated_at)
                    SELECT gen_random_uuid(), pgm.user_id, grp.project_id, grp.role, now(), now()
                    FROM project_group_members pgm
                    WHERE pgm.project_group_id = grp.id AND pgm.user_id IS NOT NULL
                    ON CONFLICT (user_id, project_id, role) DO NOTHING;

                    SELECT EXISTS (
                        SELECT 1 FROM project_group_members pgm
                        WHERE pgm.project_group_id = grp.id
                          AND (pgm.org_group_id IS NOT NULL OR pgm.source_project_id IS NOT NULL)
                    ) INTO has_extra_composition;

                    IF has_extra_composition THEN
                        -- Keeps its nested composition; no longer specially
                        -- protected — an ordinary custom group from here on.
                        UPDATE project_groups SET is_default = false WHERE id = grp.id;
                    ELSE
                        -- Fully materialized and nothing else to lose —
                        -- project_group_members rows cascade with it.
                        DELETE FROM project_groups WHERE id = grp.id;
                    END IF;
                END LOOP;
            END IF;
        END $$;
        """
    )

    op.execute("ALTER TABLE project_groups DROP COLUMN IF EXISTS is_default")


def downgrade() -> None:
    # Lossy, same as 0018's downgrade and for the same reason: which groups
    # were originally `is_default=True` is not recoverable once some of
    # them have been deleted and the rest demoted — there is no data left
    # anywhere that distinguishes a genuinely-new custom group from a
    # migrated-and-demoted former default one. The column is restored so
    # the schema matches the previous revision, defaulting every existing
    # (and future, until the corresponding model change is reverted too)
    # group to `false` rather than guessing.
    op.execute("ALTER TABLE project_groups ADD COLUMN IF NOT EXISTS is_default BOOLEAN NOT NULL DEFAULT false")
