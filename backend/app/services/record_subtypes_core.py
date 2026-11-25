"""
Module: services.record_subtypes_core

The sub-type of a record for the core artefact types, registered with `modules.registry.get_record_subtype_resolvers`
beside each module's own `record_subtypes`.

Responsibilities:
- Resolve, in bulk, the project-defined type of each action (its `ActionTypeDefinition` name), so a rule or policy can
  say "a Verification action" without naming a module.

Design decisions:
- Core owns the action type vocabulary, so core registers it here; a module registers its own types itself.
- The requirement's type is registered with the requirement types vocabulary when that exists, not here.

Dependencies: the core action models.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.action_type import ActionTypeDefinition
from app.models.requirement_action import RequirementAction
from app.modules.seams import RecordSubtypeResolver


def action_subtypes(db: Session, project_id: uuid.UUID, record_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, str]:
    """Each action's type name, for the actions of `project_id` among `record_ids`.

    Args:
        db: An active database session.
        project_id: The project the actions belong to.
        record_ids: Action ids.

    Returns:
        `{action id: action type name}`; an action with no type is absent.
    """
    rows = db.execute(
        select(RequirementAction.id, ActionTypeDefinition.name)
        .join(ActionTypeDefinition, ActionTypeDefinition.id == RequirementAction.action_type_id)
        .where(RequirementAction.id.in_(record_ids), RequirementAction.project_id == project_id)
    )
    return {action_id: name for action_id, name in rows}


CORE_RECORD_SUBTYPES: dict[str, RecordSubtypeResolver] = {"requirement_action": action_subtypes}
