"""System Architecture notes in state machine diagrams

Revision ID: 0196
Revises: 0195
Create Date: 2026-11-16

A note belongs to a block diagram or to a state machine diagram, exactly one: `architecture_diagram_notes.diagram_id`
becomes nullable and `state_machine_diagram_id` is added (deleting the state machine diagram deletes its notes), with a
check that exactly one is set. A leader gains `state_id` and `transition_id` (deleting the state or transition deletes the
leader, the note stays) and the kinds `state` and `transition`; its target check now needs the column of its own kind and no
other. Every existing note and leader is a block diagram's and is unchanged.

The downgrade removes the state machine diagrams' notes and their leaders (a block diagram has nowhere to keep them), then
restores the earlier columns and checks.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0196"
down_revision: str | None = "0195"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE architecture_diagram_notes ALTER COLUMN diagram_id DROP NOT NULL")
    op.execute(
        "ALTER TABLE architecture_diagram_notes ADD COLUMN IF NOT EXISTS state_machine_diagram_id UUID "
        "REFERENCES architecture_state_machine_diagrams(id) ON DELETE CASCADE"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_architecture_diagram_notes_state_machine_diagram_id "
        "ON architecture_diagram_notes (state_machine_diagram_id)"
    )
    op.execute("ALTER TABLE architecture_diagram_notes DROP CONSTRAINT IF EXISTS ck_architecture_diagram_notes_one_owner")
    op.execute(
        "ALTER TABLE architecture_diagram_notes ADD CONSTRAINT ck_architecture_diagram_notes_one_owner "
        "CHECK ((diagram_id IS NULL) <> (state_machine_diagram_id IS NULL))"
    )
    op.execute(
        "ALTER TABLE architecture_note_leaders ADD COLUMN IF NOT EXISTS state_id UUID "
        "REFERENCES architecture_states(id) ON DELETE CASCADE"
    )
    op.execute(
        "ALTER TABLE architecture_note_leaders ADD COLUMN IF NOT EXISTS transition_id UUID "
        "REFERENCES architecture_transitions(id) ON DELETE CASCADE"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_architecture_note_leaders_state_id ON architecture_note_leaders (state_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_architecture_note_leaders_transition_id ON architecture_note_leaders (transition_id)")
    _leader_checks(with_states=True)


def downgrade() -> None:
    op.execute(
        "DELETE FROM architecture_diagram_notes WHERE state_machine_diagram_id IS NOT NULL"
    )  # their leaders go with them (cascade)
    op.execute("DELETE FROM architecture_note_leaders WHERE kind IN ('state', 'transition')")
    _leader_checks(with_states=False)
    op.execute("DROP INDEX IF EXISTS ix_architecture_note_leaders_transition_id")
    op.execute("DROP INDEX IF EXISTS ix_architecture_note_leaders_state_id")
    op.execute("ALTER TABLE architecture_note_leaders DROP COLUMN IF EXISTS transition_id")
    op.execute("ALTER TABLE architecture_note_leaders DROP COLUMN IF EXISTS state_id")
    op.execute("ALTER TABLE architecture_diagram_notes DROP CONSTRAINT IF EXISTS ck_architecture_diagram_notes_one_owner")
    op.execute("DROP INDEX IF EXISTS ix_architecture_diagram_notes_state_machine_diagram_id")
    op.execute("ALTER TABLE architecture_diagram_notes DROP COLUMN IF EXISTS state_machine_diagram_id")
    op.execute("ALTER TABLE architecture_diagram_notes ALTER COLUMN diagram_id SET NOT NULL")


def _leader_checks(*, with_states: bool) -> None:
    """Replaces the leader's kind and target checks with the set that allows (or, for the downgrade, refuses) states and transitions."""
    op.execute("ALTER TABLE architecture_note_leaders DROP CONSTRAINT IF EXISTS ck_architecture_note_leaders_kind")
    op.execute("ALTER TABLE architecture_note_leaders DROP CONSTRAINT IF EXISTS ck_architecture_note_leaders_target")
    kinds = "'element', 'connection', 'state', 'transition', 'point'" if with_states else "'element', 'connection', 'point'"
    op.execute(f"ALTER TABLE architecture_note_leaders ADD CONSTRAINT ck_architecture_note_leaders_kind CHECK (kind IN ({kinds}))")
    state_terms = (
        " AND (kind = 'state') = (state_id IS NOT NULL) AND (kind = 'transition') = (transition_id IS NOT NULL)"
        if with_states else ""
    )
    op.execute(
        "ALTER TABLE architecture_note_leaders ADD CONSTRAINT ck_architecture_note_leaders_target CHECK ("
        "(kind = 'element') = (element_id IS NOT NULL) AND (kind = 'connection') = (connection_id IS NOT NULL)"
        f"{state_terms}"
        " AND (kind = 'point') = (x IS NOT NULL AND y IS NOT NULL) AND (kind = 'point' OR (x IS NULL AND y IS NULL)))"
    )
