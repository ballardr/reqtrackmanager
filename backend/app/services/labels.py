"""
Module: services.labels

Human-readable, sentence-cased labels for core enum wire values that render
directly into user-facing output — the generated PDF/CSV reports
(`services/reports.py`). Mirrors the frontend's equivalent maps in
`frontend/src/api/types.ts`; kept in sync by hand since the two run in
different languages, not generated from one shared source.

Casing follows the Australian Government Style Manual's "minimal
capitalisation" rule (sentence case: capitalise only the first word).

Module-owned enums (e.g. Compliance's `ComplianceStatus` and friends) keep
their own label maps under their module instead — see `modules.compliance.
labels` — rather than living here, so a module's display concerns stay next
to its data/service/router/schema layers rather than requiring a core-file
edit for a module-only enum.
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
