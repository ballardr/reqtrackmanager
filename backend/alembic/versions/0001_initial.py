"""Initial schema (Ossa v1 + Pelion v2 baseline)

Revision ID: 0001
Revises:
Create Date: 2026-07-31

Creates the full schema in one migration, using
`Base.metadata.create_all`/`drop_all` (rather than transcribing every
`op.create_table` call by hand) to stay in lockstep with the SQLAlchemy
models, which remain the single source of truth for the schema.

Note: `Base.metadata.create_all()` always reflects the *current* state of
the model classes, not a frozen snapshot from whenever this migration was
first written. That's fine for adding brand-new tables in a later migration
(scope that migration's `create_all(tables=[...])` to just the new ones),
but it means this migration must never be left in place unmodified once a
later migration also `ALTER`s a column onto one of these same tables —
`create_all` would create that column here too, and the later migration's
`op.add_column` would then fail with "column already exists". Originally
this was the Ossa (v1) baseline only; when Pelion (v2) added columns to
several v1 tables (users, organizations, projects, requirement_versions,
change_request_versions) rather than only new tables, this baseline was
squashed to include them directly instead of chasing that failure mode —
reasonable pre-release (no real deployments yet to preserve an incremental
path for). Once this project has real deployed data, schema changes must go
back to being genuinely incremental `op.add_column`/`op.create_table`
migrations, generated with `alembic revision --autogenerate`.
"""

from typing import Sequence, Union

from alembic import op

import app.models  # noqa: F401  (populates Base.metadata)
from app.database import Base

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
