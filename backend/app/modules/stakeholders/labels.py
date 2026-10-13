"""
Module: modules.stakeholders.labels

Human-readable labels for the Stakeholders & Personas enum wire values, for reports
and API consumers. Mirrors the frontend's label maps in
`frontend/src/modules/stakeholders/types.ts` by hand (the same split the other
modules use). Lookups fall back to the raw value so a newly added member renders
rather than crashing.
"""

from __future__ import annotations

TARGET_CADENCE_LABEL: dict[str, str] = {
    "one_off": "One-off",
    "ad_hoc": "Ad hoc",
    "weekly": "Weekly",
    "monthly": "Monthly",
    "quarterly": "Quarterly",
    "yearly": "Yearly",
}

ENGAGEMENT_CHANNEL_LABEL: dict[str, str] = {
    "email": "Email",
    "call": "Call",
    "meeting": "Meeting",
    "workshop": "Workshop",
    "interview": "Interview",
    "focus_group": "Focus group",
    "usability_test": "Usability test",
    "survey": "Survey",
}

GRID_QUADRANT_LABEL: dict[str, str] = {
    "manage_closely": "Manage closely",
    "keep_satisfied": "Keep satisfied",
    "keep_informed": "Keep informed",
    "monitor": "Monitor",
}

RECORD_STATUS_LABEL: dict[str, str] = {
    "draft": "Draft",
    "active": "Active",
    "retired": "Retired",
}

REQUIREMENT_STATUS_LABEL: dict[str, str] = {
    "draft": "Draft",
    "reviewed": "Reviewed",
    "approved": "Approved",
    "archived": "Archived",
}


def label(labels: dict[str, str], value: str | None) -> str:
    """The label for a wire value, the raw value when unknown, and "" for `None`."""
    return "" if value is None else labels.get(value, value)
