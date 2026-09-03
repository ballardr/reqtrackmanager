"""
Module: services.labels

Human-readable, sentence-cased labels for enum wire values that render
directly into user-facing output — currently just the generated PDF/CSV
reports (`services/reports.py`). Mirrors the frontend's equivalent maps in
`frontend/src/api/types.ts`; kept in sync by hand since the two run in
different languages, not generated from one shared source.

Casing follows the Australian Government Style Manual's "minimal
capitalisation" rule (sentence case: capitalise only the first word).
"""

from __future__ import annotations

REQUIREMENT_STATUS_LABEL: dict[str, str] = {
    "draft": "Draft",
    "reviewed": "Reviewed",
    "approved": "Approved",
    "archived": "Archived",
}


def requirement_status_label(value: str) -> str:
    return REQUIREMENT_STATUS_LABEL.get(value, value)
