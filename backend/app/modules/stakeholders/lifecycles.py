"""
Module: modules.stakeholders.lifecycles

The status path of a Persona, a Stakeholder and a Stakeholder Need as `LifecycleDefinition`s, so the lifecycle engine
(`services.lifecycles`) holds every state path of the product and every status move goes through one check.

Responsibilities:
- Build each definition from the type's `ALLOWED_TRANSITIONS` in `service` (one source) with the formal labels.
- Declare the path Draft, Active, Retired. No state is optional (Retired is reachable from Draft, and a record with no
  Active state would make the status meaningless) and none is gated, because no move needs a second person's decision.
- Give each type the step entry check its status endpoints make, so a skip of steps could never pass a step the person
  could not enter.

Design decisions:
- A Persona or Stakeholder owned by the organisation has no project to configure and keeps the full path; the entry
  check is the project-scope owner role, the right the project routes demand.

Dependencies: `service` (the transition maps), `labels`, `_shared`, `_stakeholder_shared`, `_need_shared` (the role checks),
`services.lifecycles`.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable

from sqlalchemy.orm import Session

from app.models.project import Project
from app.models.user import User
from app.modules.registry import LifecycleDefinition
from app.modules.stakeholders import _need_shared, _shared, _stakeholder_shared
from app.modules.stakeholders import service as s
from app.modules.stakeholders.enums import PersonaScope, StakeholderScope
from app.modules.stakeholders.labels import RECORD_STATUS_LABEL
from app.services.lifecycles import table_from_enum

_PATH = ("draft", "active", "retired")


def _persona_guard(db: Session, user: User, project: Project, record_id: uuid.UUID, state: str) -> None:
    """Refuses (403) a person who may not manage Personas in the project."""
    _shared.require_persona_manage(db, user, PersonaScope.PROJECT, organization_id=project.organization_id, project_id=project.id)


def _stakeholder_guard(db: Session, user: User, project: Project, record_id: uuid.UUID, state: str) -> None:
    """Refuses (403) a person who may not manage Stakeholders in the project."""
    _stakeholder_shared.require_stakeholder_manage(
        db, user, StakeholderScope.PROJECT, organization_id=project.organization_id, project_id=project.id,
    )


def _need_guard(db: Session, user: User, project: Project, record_id: uuid.UUID, state: str) -> None:
    """Refuses (403) a person who may not manage Stakeholder Needs in the project."""
    _need_shared.require_need_manage(db, user, project)


def _definition(
    label: str, transitions: dict, guard: Callable[[Session, User, Project, uuid.UUID, str], None],
) -> LifecycleDefinition:
    return LifecycleDefinition(
        label=label, path=_PATH, transitions=table_from_enum(transitions), labels=RECORD_STATUS_LABEL, entry_guard=guard,
    )


LIFECYCLES: dict[str, LifecycleDefinition] = {
    s.PERSONA_ARTEFACT_TYPE: _definition("Persona", s.PERSONA_ALLOWED_TRANSITIONS, _persona_guard),
    s.STAKEHOLDER_ARTEFACT_TYPE: _definition("Stakeholder", s.STAKEHOLDER_ALLOWED_TRANSITIONS, _stakeholder_guard),
    s.NEED_ARTEFACT_TYPE: _definition("Stakeholder Need", s.NEED_ALLOWED_TRANSITIONS, _need_guard),
}
