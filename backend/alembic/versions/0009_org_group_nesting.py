"""Org group nesting

Revision ID: 0009
Revises: 0008
Create Date: 2026-08-16

Lets an `OrgGroup` contain another `OrgGroup` as a member
(`OrgGroupMember.member_org_group_id`), transitively resolved (see
`app/services/rbac.py`'s `_ancestor_org_group_ids`/`_descendant_org_group_ids`)
— a distinct, new relationship from the existing (and deliberately
one-level-deep) org-group-in-*project*-group nesting (C-U-12).

`user_id` becomes nullable (exactly one of `user_id`/`member_org_group_id`
must be set, enforced by `ck_org_group_member_exactly_one_target`) and the
existing single-column unique constraint gets an explicit name so both a
freshly `create_all()`-built database and an upgraded one converge on the
same schema — done via `pg_constraint` existence checks rather than
`IF NOT EXISTS` (which Postgres's `ALTER TABLE ... ADD/RENAME CONSTRAINT`
doesn't support), same idempotency goal as every other migration here.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE org_group_members ADD COLUMN IF NOT EXISTS member_org_group_id "
        "UUID REFERENCES org_groups(id) ON DELETE CASCADE"
    )
    op.execute("ALTER TABLE org_group_members ALTER COLUMN user_id DROP NOT NULL")
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'org_group_members_org_group_id_user_id_key') THEN
                ALTER TABLE org_group_members
                    RENAME CONSTRAINT org_group_members_org_group_id_user_id_key TO uq_org_group_member_user;
            END IF;
        END $$;
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_org_group_member_nested_group') THEN
                ALTER TABLE org_group_members
                    ADD CONSTRAINT uq_org_group_member_nested_group UNIQUE (org_group_id, member_org_group_id);
            END IF;
        END $$;
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_org_group_member_exactly_one_target') THEN
                ALTER TABLE org_group_members
                    ADD CONSTRAINT ck_org_group_member_exactly_one_target
                    CHECK ((user_id IS NOT NULL)::int + (member_org_group_id IS NOT NULL)::int = 1);
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE org_group_members DROP CONSTRAINT IF EXISTS ck_org_group_member_exactly_one_target")
    op.execute("ALTER TABLE org_group_members DROP CONSTRAINT IF EXISTS uq_org_group_member_nested_group")
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_org_group_member_user') THEN
                ALTER TABLE org_group_members
                    RENAME CONSTRAINT uq_org_group_member_user TO org_group_members_org_group_id_user_id_key;
            END IF;
        END $$;
        """
    )
    op.execute("ALTER TABLE org_group_members ALTER COLUMN user_id SET NOT NULL")
    op.execute("ALTER TABLE org_group_members DROP COLUMN IF EXISTS member_org_group_id")
