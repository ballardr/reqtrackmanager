"""Subscriptions name a principal, so a group can watch a record

Revision ID: 0085
Revises: 0084
Create Date: 2026-10-13

`subscriptions.user_id` becomes `subscriber_id`, with a `subscriber_type`
(existing rows backfill to `user`): the subscriber may now be an organisation
group or a project group, in which case every member who can view the project
is a subscriber (resolved when a notification is sent). The foreign key to
`users` is dropped (the id now points at one of three tables), the uniqueness
moves to `(subscriber_type, subscriber_id, entity_type, entity_id)` and a check
constraint keeps the type valid.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0085"
down_revision: str | None = "0084"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TYPES = "'user', 'org_group', 'project_group'"


def upgrade() -> None:
    op.execute("ALTER TABLE subscriptions DROP CONSTRAINT IF EXISTS subscriptions_user_id_fkey")
    op.execute("ALTER TABLE subscriptions DROP CONSTRAINT IF EXISTS subscriptions_user_id_entity_type_entity_id_key")
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM information_schema.columns "
        "WHERE table_name = 'subscriptions' AND column_name = 'user_id') THEN "
        "ALTER TABLE subscriptions RENAME COLUMN user_id TO subscriber_id; END IF; END $$"
    )
    op.execute("ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS subscriber_type VARCHAR(20)")
    op.execute("UPDATE subscriptions SET subscriber_type = 'user' WHERE subscriber_type IS NULL")
    op.execute("ALTER TABLE subscriptions ALTER COLUMN subscriber_type SET NOT NULL")
    op.execute("ALTER TABLE subscriptions DROP CONSTRAINT IF EXISTS ck_subscriber_principal")
    op.execute(f"ALTER TABLE subscriptions ADD CONSTRAINT ck_subscriber_principal CHECK (subscriber_type IN ({_TYPES}))")
    op.execute("ALTER TABLE subscriptions DROP CONSTRAINT IF EXISTS uq_subscriptions_subscriber_entity")
    op.execute(
        "ALTER TABLE subscriptions ADD CONSTRAINT uq_subscriptions_subscriber_entity "
        "UNIQUE (subscriber_type, subscriber_id, entity_type, entity_id)"
    )


def downgrade() -> None:
    # Lossy: group subscriptions are dropped (they have no user to point at), and the user
    # foreign key is restored only for the user rows that remain.
    op.execute("DELETE FROM subscriptions WHERE subscriber_type <> 'user'")
    op.execute("ALTER TABLE subscriptions DROP CONSTRAINT IF EXISTS uq_subscriptions_subscriber_entity")
    op.execute("ALTER TABLE subscriptions DROP CONSTRAINT IF EXISTS ck_subscriber_principal")
    op.execute("ALTER TABLE subscriptions DROP COLUMN IF EXISTS subscriber_type")
    op.execute("ALTER TABLE subscriptions RENAME COLUMN subscriber_id TO user_id")
    op.execute(
        "ALTER TABLE subscriptions ADD CONSTRAINT subscriptions_user_id_entity_type_entity_id_key "
        "UNIQUE (user_id, entity_type, entity_id)"
    )
    op.execute("ALTER TABLE subscriptions ADD CONSTRAINT subscriptions_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id)")
