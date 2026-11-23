"""AI approval via MCP: org+project opt-in (docs/decisions.md "AI approval via MCP")

Revision ID: 0040
Revises: 0039
Create Date: 2026-09-16

Adds the two-level opt-in gate that lets an AI assistant acting through the MCP server (mcp-server/)
perform an approval-type action (approve a requirement, decide a change request, complete a
requirement). Both the organisation's and the project's flag must be true; neither alone is sufficient
(see the `Organization.allow_ai_approvals` and `Project.allow_ai_approvals` docstrings and the decisions
entry).

One boolean column on `organizations` and one on `projects`, `NOT NULL DEFAULT false`, so existing
organisations and projects have AI approval disabled, as with 0039's link-lock columns. No backfill.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0040"
down_revision: str | None = "0039"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE organizations ADD COLUMN IF NOT EXISTS allow_ai_approvals BOOLEAN NOT NULL DEFAULT false")
    op.execute("ALTER TABLE projects ADD COLUMN IF NOT EXISTS allow_ai_approvals BOOLEAN NOT NULL DEFAULT false")


def downgrade() -> None:
    op.execute("ALTER TABLE projects DROP COLUMN IF EXISTS allow_ai_approvals")
    op.execute("ALTER TABLE organizations DROP COLUMN IF EXISTS allow_ai_approvals")
