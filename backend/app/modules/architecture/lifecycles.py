"""
Module: modules.architecture.lifecycles

The status path of an element, a connection, a diagram and a state machine diagram as `LifecycleDefinition`s, so a project
can turn off Proposed and an organisation can require it (`services.lifecycles`), and so the settings, the move check and
the record's offered moves all read one source.

Responsibilities:
- Build each definition from `transitions.STATUS_MOVES` (the one map of legal moves) with the formal labels.
- Declare Proposed optional; Active and Retired are the end of the path, Rejected is off the path; nothing is gated, because
  no move needs a second person's decision.
- `ProjectMoves`: the moves a record in a status may make in a project, once the project's turned-off states are
  stepped over (what a record's "Change status" menu offers and the move endpoints accept), resolved once per project.

Design decisions:
- The step entry check of a type is the right its status endpoint demands (the Architect role or the type's manage
  permission), so a skip of steps never lets a person pass a step they could not enter.
- An organisation-owned element has no project to configure, so it keeps the full map.

Dependencies: `transitions`, `labels`, `_shared` (the role check), `services.lifecycles`.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable

from sqlalchemy.orm import Session

from app.models.project import Project
from app.models.user import User
from app.modules.architecture import _shared
from app.modules.architecture.labels import RECORD_STATUS_LABEL
from app.modules.architecture.service import (
    CONNECTION_ARTEFACT_TYPE,
    DIAGRAM_ARTEFACT_TYPE,
    ELEMENT_ARTEFACT_TYPE,
    STATE_MACHINE_ARTEFACT_TYPE,
)
from app.modules.architecture.transitions import STATUS_MOVES, allowed_moves
from app.modules.registry import LifecycleDefinition
from app.services.lifecycles import ResolvedLifecycle, lifecycle_for, next_states, table_from_enum

_PATH = ("draft", "proposed", "active", "retired")


def _entry_guard(permission: str) -> Callable[[Session, User, Project, uuid.UUID, str], None]:
    """The step entry check of a type whose status endpoint needs `permission` (or the Architect role)."""

    def guard(db: Session, user: User, project: Project, record_id: uuid.UUID, state: str) -> None:
        _shared.require_architect(db, user, project, permission)

    return guard


def _definition(label: str, permission: str) -> LifecycleDefinition:
    return LifecycleDefinition(
        label=label, path=_PATH, transitions=table_from_enum(STATUS_MOVES), labels=RECORD_STATUS_LABEL,
        optional=("proposed",), entry_guard=_entry_guard(permission),
    )


LIFECYCLES: dict[str, LifecycleDefinition] = {
    ELEMENT_ARTEFACT_TYPE: _definition("Element", _shared.ELEMENT_MANAGE_PERMISSION),
    CONNECTION_ARTEFACT_TYPE: _definition("Connection", _shared.CONNECTION_MANAGE_PERMISSION),
    DIAGRAM_ARTEFACT_TYPE: _definition("Diagram", _shared.DIAGRAM_MANAGE_PERMISSION),
    STATE_MACHINE_ARTEFACT_TYPE: _definition("State machine diagram", _shared.STATE_MACHINE_MANAGE_PERMISSION),
}


class ProjectMoves:
    """The moves a record may make, resolved once per project for a list of records of one type.

    Attributes:
        db: Active session (read only).
        artefact_type: The record type.
    """

    def __init__(self, db: Session, artefact_type: str) -> None:
        self.db = db
        self.artefact_type = artefact_type
        self._resolved: dict[uuid.UUID, ResolvedLifecycle] = {}

    def of(self, project_id: uuid.UUID | None, status: str) -> list[str]:
        """The statuses a record in `status` may be moved to in `project_id`.

        Args:
            project_id: The record's project, `None` for an organisation-owned element, which keeps the full map.
            status: The record's current status.

        Returns:
            The legal next statuses in the order of `transitions.STATUS_MOVES` (the menu order), with a turned-off status
            replaced by the statuses beyond it.
        """
        if project_id is None:
            return allowed_moves(status)
        if project_id not in self._resolved:
            self._resolved[project_id] = lifecycle_for(self.db, project_id, self.artefact_type)
        effective = next_states(self._resolved[project_id], status)
        listed = allowed_moves(status)
        return [m for m in listed if m in effective] + [m for m in effective if m not in listed]
