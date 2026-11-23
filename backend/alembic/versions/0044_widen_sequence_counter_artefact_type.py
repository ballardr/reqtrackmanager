"""Make ProjectSequenceCounter.artefact_type module-registrable

Revision ID: 0044
Revises: 0043
Create Date: 2026-09-21

Widens `project_sequence_counters.artefact_type` from VARCHAR(20) to VARCHAR(40), matching
`artefact_links.source_type`/`target_type`, because the column is a plain string validated against
`app.modules.registry.get_all_registered_artefact_types()` instead of a fixed `models.enums.ArtefactType`
member (see `app.models.sequence.ProjectSequenceCounter` and docs/decisions.md's "Decision Management
- ProjectSequenceCounter made module-registrable" entry).

Only the declared length changes: the existing values (`"requirement"`, `"requirement_action"`; no rows
exist per 0042) fit in 40 characters.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0044"
down_revision: str | None = "0043"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE project_sequence_counters ALTER COLUMN artefact_type TYPE VARCHAR(40)")


def downgrade() -> None:
    # Safe to narrow back: every artefact_type value in use today
    # ("requirement", "requirement_action") fits in 20 characters, and this
    # table has no rows from any other source (see module docstring).
    op.execute("ALTER TABLE project_sequence_counters ALTER COLUMN artefact_type TYPE VARCHAR(20)")
