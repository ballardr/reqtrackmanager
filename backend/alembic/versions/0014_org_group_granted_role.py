"""Org group granted role

Revision ID: 0014
Revises: 0013
Create Date: 2026-08-25

2026-08 UX audit roadmap item 522: role-granting via an SSO group claim
should be a property of the `OrgGroup` being synced into, not a
disconnected flat list (`Organization.sso_group_mappings`, a JSONB list of
`{"sso_group": ..., "org_role": ...}` entries with no relationship to
`OrgGroup` at all). Adds `org_groups.granted_org_role`, backfills it from
every existing `sso_group_mappings` entry — matched against an existing
`OrgGroup` with the same `idp_synced_group_name` where one already exists,
or a newly created one (named after the SSO group string) where it doesn't
— then retires `organizations.sso_group_mappings` entirely.

Migration decision, made explicit here since the roadmap item itself
flagged this as needing one: `granted_org_role` is a single nullable
column, not a list, so an organisation that (unusually — not exercised by
any existing test or seed data, confirmed by grep before writing this)
mapped the same `sso_group` string to two different `org_role`s across two
separate `sso_group_mappings` entries can only carry one forward; the later
entry in stored array order wins, deterministically, rather than silently
picking one. This is a real, narrow behaviour change for that one edge
case, not a bug — the new model doesn't have a way to represent "this one
IdP group grants two different org roles," which the old flat list
technically permitted.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE org_groups ADD COLUMN IF NOT EXISTS granted_org_role VARCHAR(30)")

    # Guarded the same way 0012's `link_type` backfill is: only a database
    # migrated from before this revision ever has `sso_group_mappings` to
    # read from — a brand-new database's 0001_initial.py already builds
    # from the current models, which never had this column.
    op.execute(
        """
        DO $$
        DECLARE
            org_row RECORD;
            mapping JSONB;
            existing_group_id UUID;
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'organizations' AND column_name = 'sso_group_mappings'
            ) THEN
                FOR org_row IN SELECT id, sso_group_mappings FROM organizations WHERE jsonb_array_length(sso_group_mappings) > 0
                LOOP
                    FOR mapping IN SELECT * FROM jsonb_array_elements(org_row.sso_group_mappings)
                    LOOP
                        SELECT id INTO existing_group_id
                        FROM org_groups
                        WHERE organization_id = org_row.id
                          AND idp_synced_group_name = (mapping->>'sso_group')
                        LIMIT 1;

                        IF existing_group_id IS NOT NULL THEN
                            UPDATE org_groups SET granted_org_role = (mapping->>'org_role')
                            WHERE id = existing_group_id;
                        ELSE
                            INSERT INTO org_groups (id, created_at, updated_at, organization_id, name, idp_synced_group_name, granted_org_role)
                            VALUES (
                                gen_random_uuid(), now(), now(), org_row.id,
                                (mapping->>'sso_group'), (mapping->>'sso_group'), (mapping->>'org_role')
                            );
                        END IF;
                    END LOOP;
                END LOOP;
            END IF;
        END $$;
        """
    )

    op.execute("ALTER TABLE organizations DROP COLUMN IF EXISTS sso_group_mappings")


def downgrade() -> None:
    op.execute("ALTER TABLE organizations ADD COLUMN IF NOT EXISTS sso_group_mappings JSONB NOT NULL DEFAULT '[]'")
    op.execute(
        """
        UPDATE organizations o
        SET sso_group_mappings = COALESCE(
            (
                SELECT jsonb_agg(jsonb_build_object('sso_group', g.idp_synced_group_name, 'org_role', g.granted_org_role))
                FROM org_groups g
                WHERE g.organization_id = o.id AND g.granted_org_role IS NOT NULL
            ),
            '[]'::jsonb
        )
        """
    )
    op.execute("ALTER TABLE org_groups DROP COLUMN IF EXISTS granted_org_role")
