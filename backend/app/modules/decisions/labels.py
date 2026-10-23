"""
Module: modules.decisions.labels

Human-readable labels for Decision Management's enum wire values, read by
`reports.py` when rendering PDF/CSV/JSON reports. Mirrors the frontend's
`DECISION_STATUS_LABEL` (`frontend/src/modules/decisions/types.ts`) by hand,
the same split `modules.context_strategy.labels` uses. Lookups fall back to
the raw value so a newly added status renders rather than crashing a report.
"""

from __future__ import annotations

DECISION_STATUS_LABEL: dict[str, str] = {
    "draft": "Draft",
    "proposed": "Proposed",
    "under_review": "Under review",
    "approved": "Approved",
    "rejected": "Rejected",
    "superseded": "Superseded",
}

# Badge tone per status, mirroring `DECISION_STATUS_TONE` in `frontend/src/modules/decisions/types.ts` by hand (a test pins the two).
DECISION_STATUS_TONE: dict[str, str] = {
    "draft": "muted",
    "proposed": "info",
    "under_review": "info",
    "approved": "accent",
    "rejected": "danger",
    "superseded": "muted",
}


def decision_status_label(value: str) -> str:
    """Returns the display label for a `DecisionStatus` value (the raw value if unmapped)."""
    return DECISION_STATUS_LABEL.get(value, value)
