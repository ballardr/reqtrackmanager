"""
Module: modules.decisions.activity_links

Reads the two records a Decision link audit event joins, for the History page and the record Activity aside
(`ModuleDefinition.activity_link_ends`).

Responsibilities:
- Turn a `decision_link` event's `detail` into its source and target records and the relationship's forward name.

Design decisions:
- Three shapes are logged: Decision to Requirement (`decision_id`, `requirement_id`), Decision to Decision
  (`source_decision_id`, `target_decision_id`) and supersession (`new_decision_id`, `old_decision_id`). The
  relationship name is the one the link is created with, from `kind`.
- Every value is parsed defensively; an unreadable event yields no ends rather than an error.

External dependencies: `modules.decisions.service` (the relationship names), `modules.registry`.
"""

from __future__ import annotations

import uuid
from typing import Any

from app.models.enums import ArtefactType
from app.modules.decisions import service
from app.modules.registry import ActivityLinkEnds

#: Event entity type this module logs for every link it creates.
LINK_EVENT_TYPE = "decision_link"

_NAMES: dict[str, str] = {
    **{kind.value: names[0] for kind, names in service._DECISION_REQUIREMENT_LINK_NAMES.items()},
    **{kind.value: names[0] for kind, names in service._DECISION_DECISION_LINK_NAMES.items()},
    "supersession": service.SUPERSEDES_LINK_TYPE_FORWARD_NAME,
}


def _uuid(value: Any) -> uuid.UUID | None:
    """A UUID from an audit detail value, else `None`."""
    try:
        return uuid.UUID(str(value))
    except ValueError:
        return None


def link_ends(detail: dict[str, Any]) -> ActivityLinkEnds | None:
    """The ends of one `decision_link` event.

    Args:
        detail: The event's audit detail.

    Returns:
        The source and target records and the relationship's forward name, or `None` when the detail names no pair.
    """
    label = _NAMES.get(str(detail.get("kind")))
    decision = service.DECISION_ARTEFACT_TYPE
    pairs = (
        ("decision_id", decision, "requirement_id", ArtefactType.REQUIREMENT.value),
        ("source_decision_id", decision, "target_decision_id", decision),
        ("new_decision_id", decision, "old_decision_id", decision),
    )
    for source_key, source_type, target_key, target_type in pairs:
        source_id, target_id = _uuid(detail.get(source_key)), _uuid(detail.get(target_key))
        if source_id is not None and target_id is not None:
            return ActivityLinkEnds((source_type, source_id), (target_type, target_id), link_type_label=label)
    return None
