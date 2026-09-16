"""AI approval via MCP: org+project opt-in (docs/decisions.md "AI approval via MCP")

Revision ID: 0040
Revises: 0039
Create Date: 2026-09-16

Adds the two-level opt-in gate that lets an AI assistant acting through the
MCP server (mcp-server/) perform an approval-type action (approve a
requirement, decide a change request, complete a requirement) — previously
structurally impossible in every case, in either MCP mode. Both the
organisation's and the project's own flag must be true for the gate to pass;
neither one alone is sufficient. See Organization.allow_ai_approvals and
Project.allow_ai_approvals docstrings for the full mechanism, and
docs/decisions.md's "AI approval via MCP" entry for why this reopens a
previously non-negotiable exclusion.

One new boolean column on `organizations` and one on `projects`, both
`NOT NULL DEFAULT false` — additive-only, so every existing org/project
starts with AI approval disabled, matching the permissive-default-off
convention 0039's own link-lock columns already established. No backfill
needed.
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
