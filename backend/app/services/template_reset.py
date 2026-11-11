"""
Module: services.template_reset

Returns a module's exported starter records to a fresh-draft state when a project is created from a
template (see `services.template_content`). Kept dependency-free so every module's export file can
import it without a cycle.

The same reset removes imported approval state when an organisation does not allow it
(`services.bundle_approval_state`). There it runs inside `keeping_history()`, which keeps archived records and
their authorship, since an import is not a template: only approvals, decisions, reviews and votes are removed.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

_keep_history: ContextVar[bool] = ContextVar("template_reset_keep_history", default=False)


@contextmanager
def keeping_history() -> Iterator[None]:
    """Within the block, resets keep archived records and each record's creator and creation time."""
    token = _keep_history.set(True)
    try:
        yield
    finally:
        _keep_history.reset(token)


def is_retired(entry: dict[str, Any]) -> bool:
    """Whether a reset leaves `entry` out: an archived record, except while `keeping_history()`."""
    return bool(entry.get("is_archived")) and not _keep_history.get()


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
    keep = _keep_history.get()
    entries[:] = [e for e in entries if not is_retired(e)]
    for entry in entries:
        if not keep:
            entry.update(created_by_email=None, created_at=None, is_archived=False, archived_at=None, archived_by_email=None)
        if status is not None:
            entry["status"] = status
        for key in clear:
            entry[key] = None
        for key in empty:
            entry[key] = []
