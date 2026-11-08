"""
Module: services.template_reset

Returns a module's exported starter records to a fresh-draft state when a project is created from a
template (see `services.template_content`). Kept dependency-free so every module's export file can
import it without a cycle.
"""

from __future__ import annotations

from typing import Any


def fresh_drafts(
    entries: list[dict[str, Any]], *, status: str | None = None, clear: tuple[str, ...] = (), empty: tuple[str, ...] = (),
) -> None:
    """Returns exported starter records to a fresh-draft state, in place.

    Archived entries are removed (a template's retired records are not a starting point). Every
    remaining entry loses its creator and creation time (the importer becomes the creator) and, when
    `status` is given, takes it.

    Args:
        entries: The exported entries of one record list; modified in place.
        status: The module's initial status value, or `None` when the entries carry none.
        clear: Keys set to `None` (dates, reasons, markers belonging to the template's own history).
        empty: Keys set to an empty list (reviews, treatments, scores, informed parties).
    """
    entries[:] = [e for e in entries if not e.get("is_archived")]
    for entry in entries:
        entry.update(created_by_email=None, created_at=None, is_archived=False, archived_at=None, archived_by_email=None)
        if status is not None:
            entry["status"] = status
        for key in clear:
            entry[key] = None
        for key in empty:
            entry[key] = []
