"""
Module: modules.context_strategy.labels

Human-readable labels for this module's enum wire values, read by
`reports.py` when rendering PDF/CSV/JSON reports. Mirrors the frontend's
equivalent maps in `frontend/src/modules/context_strategy/types.ts` by hand
(the two run in different languages), the same split `modules.compliance.
labels` uses. Lookups fall back to the raw value so a newly added enum value
renders rather than crashing a report.
"""

from __future__ import annotations

PRIORITY_LABEL: dict[str, str] = {"low": "Low", "medium": "Medium", "high": "High"}

# Strategy, Future State and Guiding Principle share their lifecycle wording.
LIFECYCLE_STATUS_LABEL: dict[str, str] = {
    "draft": "Draft",
    "proposed": "Proposed",
    "under_review": "Under review",
    "approved": "Approved",
    "active": "Active",
    "superseded": "Superseded",
    "retired": "Retired",
}

PAIN_POINT_STATUS_LABEL: dict[str, str] = {
    "submitted": "Submitted",
    "triaged": "Triaged",
    "rejected": "Rejected",
    "duplicate": "Duplicate",
    "accepted": "Accepted",
    "addressed": "Addressed",
    "closed": "Closed",
}

OPEN_QUESTION_STATUS_LABEL: dict[str, str] = {
    "open": "Open",
    "investigating": "Investigating",
    "ready_for_decision": "Ready for Decision",
    "resolved": "Resolved",
    "withdrawn": "Withdrawn",
}

SCOPE_LABEL: dict[str, str] = {"organization": "Organisation", "project": "Project"}

ROLLUP_LABEL: dict[str, str] = {
    "weighted_average": "Weighted average",
    "worst_case": "Worst case",
    "average": "Plain average",
}

SCORE_TARGET_STATUS_LABEL: dict[str, str] = {
    "all": "All personas",
    "active": "Active",
    "inactive": "Retired (not counted)",
    "unavailable": "Persona unavailable",
}


def label(mapping: dict[str, str], value: str | None) -> str:
    """Returns `mapping[value]`, the raw `value` if unmapped, or `""` for `None`."""
    if value is None:
        return ""
    return mapping.get(value, value)
