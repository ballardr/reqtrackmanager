"""Initial schema (Ossa v1 + Pelion v2 baseline)

Revision ID: 0001
Revises:
Create Date: 2026-07-31

Creates the full schema with `Base.metadata.create_all`/`drop_all`, so the baseline stays in lockstep
with the SQLAlchemy models, which are the single source of truth for the schema.

`create_all()` reflects the current model classes, not a frozen snapshot, so a later migration that
adds a column to one of these tables finds it already created. Later migrations therefore scope
`create_all(tables=[...])` to new tables or use `IF NOT EXISTS`. Once real data is deployed, schema
changes are incremental `op.add_column`/`op.create_table` migrations (`alembic revision --autogenerate`).
"""

from collections.abc import Sequence

import app.models  # noqa: F401  (populates Base.metadata)
from alembic import op
from app.database import Base

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
