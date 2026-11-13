"""
Module: modules.architecture.labels

Human-readable labels for the module's enum wire values, for reports, search results and API
consumers. Mirrors the frontend's label maps in `frontend/src/modules/architecture/types.ts` by
hand. Lookups fall back to the raw value so a newly added member renders rather than crashing.
"""

from __future__ import annotations

RECORD_STATUS_LABEL: dict[str, str] = {
    "draft": "Draft",
    "proposed": "Proposed",
    "active": "Active",
    "retired": "Retired",
    "rejected": "Rejected",
}

PORT_DIRECTION_LABEL: dict[str, str] = {
    "in": "In",
    "out": "Out",
    "both": "Both",
}

#: Statuses that mean a record is no longer in force, for "Open only" filters and the inactive style.
INACTIVE_STATUSES: tuple[str, ...] = ("retired", "rejected")


def record_status_label(value: str) -> str:
    """The display label for a `RecordStatus` value (the raw value if unmapped)."""
    return RECORD_STATUS_LABEL.get(value, value)
