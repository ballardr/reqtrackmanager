"""
Module: modules.architecture.transitions

The one map of which status moves an element, a connection or a diagram may make. Every change of status goes
through `require_move`, and every record the API returns carries `allowed_moves(status)`, so the "Change state" menu
draws exactly what the server accepts.

A later state is a new entry in `STATUS_MOVES` plus a label, not a change to the frontend menu. There is no approval
step: any person who may manage the record may make any move listed here. This module is a leaf (no imports from the
rest of the package other than the enum).
"""

from __future__ import annotations

from app.modules.architecture.enums import RecordStatus

#: The moves each status offers, in menu order.
STATUS_MOVES: dict[RecordStatus, tuple[RecordStatus, ...]] = {
    RecordStatus.DRAFT: (RecordStatus.PROPOSED, RecordStatus.ACTIVE, RecordStatus.REJECTED),
    RecordStatus.PROPOSED: (RecordStatus.ACTIVE, RecordStatus.DRAFT, RecordStatus.REJECTED),
    RecordStatus.ACTIVE: (RecordStatus.RETIRED,),
    RecordStatus.RETIRED: (RecordStatus.ACTIVE,),
    RecordStatus.REJECTED: (RecordStatus.DRAFT,),
}


def allowed_moves(status: str) -> list[str]:
    """The status values a record in `status` may move to (empty for a value the map does not know)."""
    try:
        return [m.value for m in STATUS_MOVES[RecordStatus(status)]]
    except (ValueError, KeyError):
        return []


def move_refusal(current: str, target: RecordStatus) -> str | None:
    """Why a record in `current` may not move to `target`, or `None` when it may."""
    if current == target.value:
        return "The record already has this status."
    if target.value not in allowed_moves(current):
        return f"A record cannot move from {current.capitalize()} to {target.value.capitalize()}."
    return None
