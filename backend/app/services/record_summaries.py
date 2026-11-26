"""
Module: services.record_summaries

Lists and reads the summaries (id, status, archived flag) of the records of one type in one project, for every registered
artefact type: a core type through its own tables and a module's type through its `ArtefactSummaryProvider`.

Responsibilities:
- `list_summaries`: every record of a type a project holds.
- `read_summaries`: the records among a set of ids that the project may see.
- `has_summaries`: whether a type can be listed at all.

Design decisions:
- Core types (`requirement`, `requirement_action`, `change_request`) have no provider registration, so they are read here
  through `services.link_graph.core_summaries`, the reader the link graph uses; every other type goes through its module,
  which applies its own visibility and enablement rules, so core never imports a module.
- Nothing here checks the caller's permissions: a caller that shows the result to a person applies the type's `view`
  permission first.

Dependencies: `services.link_graph`, `modules.registry`, the core record models.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.change_request import ChangeRequest
from app.models.enums import CORE_ARTEFACT_TYPES, ArtefactType
from app.models.requirement import Requirement
from app.models.requirement_action import RequirementAction
from app.modules import registry
from app.modules.registry import ArtefactSummary
from app.services.link_graph import core_summaries

_CORE_ID_COLUMNS = {
    ArtefactType.REQUIREMENT.value: (Requirement.id, Requirement.project_id),
    ArtefactType.REQUIREMENT_ACTION.value: (RequirementAction.id, RequirementAction.project_id),
    ArtefactType.CHANGE_REQUEST.value: (ChangeRequest.id, ChangeRequest.project_id),
}


def has_summaries(artefact_type: str) -> bool:
    """Whether records of the type can be listed: a core type, or one a module provides summaries for."""
    return artefact_type in CORE_ARTEFACT_TYPES or registry.has_artefact_summary_provider(artefact_type)


def list_summaries(db: Session, project_id: uuid.UUID, artefact_type: str) -> list[ArtefactSummary]:
    """Every record of `artefact_type` that project `project_id` holds itself.

    Args:
        db: Active session (read only).
        project_id: The project.
        artefact_type: A registered record type.

    Returns:
        The summaries, archived records included (each carries `is_archived`); empty when the type has none, cannot be
        listed or its module is off for the project.
    """
    columns = _CORE_ID_COLUMNS.get(artefact_type)
    if columns is None:
        return [s for s in registry.list_artefact_summaries(db, project_id, artefact_type) if s.project_id == project_id]
    id_column, project_column = columns
    ids = list(db.scalars(select(id_column).where(project_column == project_id)))
    return list(core_summaries(db, [project_id], artefact_type, ids).values()) if ids else []


def read_summaries(
    db: Session, project_id: uuid.UUID, artefact_type: str, ids: Sequence[uuid.UUID],
) -> dict[uuid.UUID, ArtefactSummary]:
    """The records among `ids` that project `project_id` may see.

    Returns:
        `{id: summary}`; an id that is missing, belongs to another project or whose module is off is absent.
    """
    if not ids:
        return {}
    if artefact_type in CORE_ARTEFACT_TYPES:
        return core_summaries(db, [project_id], artefact_type, list(ids))
    return registry.get_artefact_summaries_in_project(db, project_id, artefact_type, ids) or {}
