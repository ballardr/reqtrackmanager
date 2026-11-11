"""
Module: modules.context_strategy.activity_links

Reads the two records a Context & Strategy link audit event joins, for the History page and the record Activity
aside (`ModuleDefinition.activity_link_ends`).

Responsibilities:
- Turn a `context_strategy_link` event's `detail` into its source and target records and, for a typed
  relationship, its forward name.

Design decisions:
- A plain link names its owning record under `<type>_id` plus `target_id`; the target's type and the
  relationship's name come from the same per-kind specification the link is created from, so they cannot drift.
  A supersession names `new_<type>_id` and `old_<type>_id` of one type.
- The detail is audit data written before the link existed in any later form, so every value is parsed defensively
  and an unreadable event yields no ends rather than an error.

External dependencies: `modules.context_strategy.service` (the link specifications), `modules.registry`.
"""

from __future__ import annotations

import uuid
from typing import Any

from app.modules.context_strategy import service
from app.modules.registry import ActivityLinkEnds

#: Event entity type this module logs for every link it creates.
LINK_EVENT_TYPE = "context_strategy_link"

#: `{owner detail key: (owner artefact type, {kind value: (target type, forward name)})}`.
_OWNERS: dict[str, tuple[str, dict[str, tuple[str, str | None]]]] = {
    "strategy_id": (
        service.STRATEGY_ARTEFACT_TYPE,
        {kind.value: (spec[0], spec[1]) for kind, spec in service._STRATEGY_LINK_SPECS.items()},
    ),
    "pain_point_id": (
        service.PAIN_POINT_ARTEFACT_TYPE,
        {kind.value: (spec[0], spec[1]) for kind, spec in service._PAIN_POINT_LINK_SPECS.items()},
    ),
    "guiding_principle_id": (
        service.GUIDING_PRINCIPLE_ARTEFACT_TYPE,
        {kind.value: (spec[0], spec[1]) for kind, spec in service._GUIDING_PRINCIPLE_LINK_SPECS.items()},
    ),
    "future_state_id": (
        service.FUTURE_STATE_ARTEFACT_TYPE,
        {kind.value: (spec[0], spec[1]) for kind, spec in service._FUTURE_STATE_LINK_SPECS.items()},
    ),
    "open_question_id": (
        service.OPEN_QUESTION_ARTEFACT_TYPE,
        {kind.value: (spec[0], spec[1]) for kind, spec in service._OPEN_QUESTION_LINK_SPECS.items()},
    ),
}

#: `{artefact type: its supersession name}`; a supersession is typed "Supersedes" in every type that has one.
_SUPERSESSION_LABEL = "Supersedes"


def _uuid(value: Any) -> uuid.UUID | None:
    """A UUID from an audit detail value, else `None`."""
    try:
        return uuid.UUID(str(value))
    except ValueError:
        return None


def link_ends(detail: dict[str, Any]) -> ActivityLinkEnds | None:
    """The ends of one `context_strategy_link` event.

    Args:
        detail: The event's audit detail.

    Returns:
        The source and target records (and the relationship's forward name when the kind has one), or `None`
        when the detail names no pair this module knows.
    """
    kind = detail.get("kind")
    if kind == "supersession":
        for owner_key, (artefact_type, _kinds) in _OWNERS.items():
            prefix = owner_key.removesuffix("_id")
            new_id, old_id = _uuid(detail.get(f"new_{prefix}_id")), _uuid(detail.get(f"old_{prefix}_id"))
            if new_id is not None and old_id is not None:
                return ActivityLinkEnds((artefact_type, new_id), (artefact_type, old_id), link_type_label=_SUPERSESSION_LABEL)
        return None
    for owner_key, (artefact_type, kinds) in _OWNERS.items():
        owner_id, target_id = _uuid(detail.get(owner_key)), _uuid(detail.get("target_id"))
        spec = kinds.get(str(kind))
        if owner_id is not None and target_id is not None and spec is not None:
            return ActivityLinkEnds((artefact_type, owner_id), (spec[0], target_id), link_type_label=spec[1])
    return None
