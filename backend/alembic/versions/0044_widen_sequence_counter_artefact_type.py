"""Make ProjectSequenceCounter.artefact_type module-registrable

Revision ID: 0044
Revises: 0043
Create Date: 2026-09-21

Module 4 (Decision Management), Phase 1: widens `project_sequence_
counters.artefact_type` from VARCHAR(20) to VARCHAR(40) — matching
`artefact_links.source_type`/`target_type`'s own column width — as part of
changing this column from a fixed `models.enums.ArtefactType` enum member
to a plain, module-registrable string validated against
`app.modules.registry.get_all_registered_artefact_types()`. See
`app.models.sequence.ProjectSequenceCounter`'s own docstring for the full
reasoning and `docs/decisions.md`'s "Module 4 (Decision Management) Phase 1
— ProjectSequenceCounter made module-registrable" entry.

Widening only — the two existing values this column could ever have held
(`"requirement"`, `"requirement_action"`, both unused so far per Module 0
Phase 2's own migration 0042, which backfills no rows) already fit in 40
characters, so no data rewrite is needed, only the column's declared
maximum length.
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
