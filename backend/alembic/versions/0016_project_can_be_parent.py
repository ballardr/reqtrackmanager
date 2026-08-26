"""Project can_be_parent eligibility gate

Revision ID: 0016
Revises: 0015
Create Date: 2026-08-26

Adds `projects.can_be_parent`, a manager-controlled, default-`False` gate on
whether a project may be selected as a parent for *other* projects
(`routers.projects.create_project`/`update_project` now 400 if the intended
parent has this `False`) — see docs/decisions.md's "Hierarchical projects"
entry for the follow-up decision that added this. Requested directly: the
"Parent project" picker was showing on every project even when there was
nothing eligible for the caller to actually pick, and any project the caller
merely manages could be attached to sight-unseen, with no deliberate opt-in
from that project's own manager first.

Existing parent/child relationships are grandfathered: any project that
already has at least one child (i.e. is referenced by another row's
`parent_project_id`) is backfilled to `can_be_parent = true`, so this
migration cannot retroactively break an already-established hierarchy —
only *new* attachments are gated going forward.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE projects ADD COLUMN IF NOT EXISTS can_be_parent BOOLEAN NOT NULL DEFAULT false")
    op.execute(
        """
        UPDATE projects SET can_be_parent = true
        WHERE id IN (SELECT DISTINCT parent_project_id FROM projects WHERE parent_project_id IS NOT NULL)
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE projects DROP COLUMN IF EXISTS can_be_parent")
