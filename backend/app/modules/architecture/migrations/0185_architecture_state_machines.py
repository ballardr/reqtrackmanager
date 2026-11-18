"""System Architecture state machine diagrams: diagrams, states and transitions

Revision ID: 0185
Revises: 0184
Create Date: 2026-11-14

Adds `architecture_state_machine_diagrams` (the behaviour of one element, with its own code and version),
`architecture_states` (a state or an initial, final or choice marker, with its code, its nesting and its place on the
drawing) and `architecture_transitions` (the arrows between two states of one diagram). Deleting a state machine diagram
removes its states and transitions, and deleting a state removes the transitions that start or end at it. An element
cannot be deleted while a state machine diagram describes it, and a state cannot be deleted while it has child states.
Nothing is seeded.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0185"
down_revision: str | None = "0184"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS architecture_state_machine_diagrams (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            unique_code VARCHAR(64) NOT NULL,
            name VARCHAR(200) NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            element_id UUID NOT NULL REFERENCES architecture_elements(id),
            status VARCHAR(20) NOT NULL DEFAULT 'draft',
            version INTEGER NOT NULL DEFAULT 1,
            creator_id UUID NOT NULL REFERENCES users(id),
            is_archived BOOLEAN NOT NULL DEFAULT false,
            archived_at TIMESTAMPTZ,
            archived_by UUID REFERENCES users(id),
            CONSTRAINT uq_architecture_state_machine_diagrams_project_unique_code UNIQUE (project_id, unique_code)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_architecture_state_machine_diagrams_project_id "
        "ON architecture_state_machine_diagrams (project_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_architecture_state_machine_diagrams_element_id "
        "ON architecture_state_machine_diagrams (element_id)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS architecture_states (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            state_machine_diagram_id UUID NOT NULL REFERENCES architecture_state_machine_diagrams(id) ON DELETE CASCADE,
            project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            unique_code VARCHAR(64) NOT NULL,
            name VARCHAR(200) NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            kind VARCHAR(16) NOT NULL DEFAULT 'state',
            parent_state_id UUID REFERENCES architecture_states(id),
            entry_action TEXT NOT NULL DEFAULT '',
            exit_action TEXT NOT NULL DEFAULT '',
            activity TEXT NOT NULL DEFAULT '',
            x DOUBLE PRECISION NOT NULL DEFAULT 0,
            y DOUBLE PRECISION NOT NULL DEFAULT 0,
            width DOUBLE PRECISION NOT NULL DEFAULT 160,
            height DOUBLE PRECISION NOT NULL DEFAULT 64,
            collapsed BOOLEAN NOT NULL DEFAULT false,
            creator_id UUID NOT NULL REFERENCES users(id),
            CONSTRAINT uq_architecture_states_project_unique_code UNIQUE (project_id, unique_code),
            CONSTRAINT uq_architecture_states_name UNIQUE (state_machine_diagram_id, name),
            CONSTRAINT ck_architecture_states_kind CHECK (kind IN ('initial', 'state', 'final', 'choice'))
        )
        """
    )
    for column in ("state_machine_diagram_id", "project_id", "parent_state_id"):
        op.execute(f"CREATE INDEX IF NOT EXISTS ix_architecture_states_{column} ON architecture_states ({column})")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS architecture_transitions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            state_machine_diagram_id UUID NOT NULL REFERENCES architecture_state_machine_diagrams(id) ON DELETE CASCADE,
            source_state_id UUID NOT NULL REFERENCES architecture_states(id) ON DELETE CASCADE,
            target_state_id UUID NOT NULL REFERENCES architecture_states(id) ON DELETE CASCADE,
            event VARCHAR(200) NOT NULL DEFAULT '',
            guard VARCHAR(500) NOT NULL DEFAULT '',
            action VARCHAR(500) NOT NULL DEFAULT '',
            description TEXT NOT NULL DEFAULT '',
            sort_order INTEGER NOT NULL DEFAULT 0,
            source_point VARCHAR(16),
            target_point VARCHAR(16)
        )
        """
    )
    for column in ("state_machine_diagram_id", "source_state_id", "target_state_id"):
        op.execute(f"CREATE INDEX IF NOT EXISTS ix_architecture_transitions_{column} ON architecture_transitions ({column})")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS architecture_transitions")
    op.execute("DROP TABLE IF EXISTS architecture_states")
    op.execute("DROP TABLE IF EXISTS architecture_state_machine_diagrams")
