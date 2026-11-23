"""
Module: services.artefact_changes

Tells interested modules that an artefact changed, so a dependent can be flagged for a human to re-judge
(detection and notification, not automatic rewriting). Risk Management uses it to mark a treatment verdict
for reassessment when the requirement mitigating a risk changes.

Responsibilities: `notify_artefact_changed` hands an `ArtefactChange` to every registered module's
`on_artefact_changed` hook inside the caller's transaction; `requirement_content_changed` says whether a new
requirement version altered what it says (not owner, review date or status).

Design decisions:
- A generic hook on `ModuleDefinition`, not an import of a module (Modular Feature System Boundary).
- Hooks run synchronously and must not commit, so a change and its flags are one atomic unit. A hook that
  raises is logged and skipped, so a dependent's bookkeeping never fails the triggering edit.
- Only content edits and archival raise the hook; status, owner and review-date edits do not, so flags stay
  rare enough to merit attention.

Dependencies: `app.modules.registry`.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from app.modules.registry import ArtefactChange, get_module_registry

logger = logging.getLogger(__name__)

#: The requirement version fields whose change can invalidate something that depends on it.
REQUIREMENT_CONTENT_FIELDS: tuple[str, ...] = ("name", "description", "reasoning", "clarification", "level")


def notify_artefact_changed(db: Session, change: ArtefactChange) -> None:
    """Calls every registered module's `on_artefact_changed` hook with `change`.

    Does not commit. A hook that raises is logged and skipped so the change that
    triggered it still goes through.

    Args:
        db: The caller's session (the hooks join its transaction).
        change: What changed.
    """
    for definition in get_module_registry().values():
        if definition.on_artefact_changed is None:
            continue
        try:
            with db.begin_nested():
                definition.on_artefact_changed(db, change)
        except Exception:  # noqa: BLE001 - a dependent's bookkeeping must not fail the triggering edit
            logger.exception("Module %r on_artefact_changed hook failed for %s %s",
                             definition.key, change.artefact_type, change.artefact_id)


def requirement_content_changed(previous: Any, updated: Any) -> list[str]:
    """The `REQUIREMENT_CONTENT_FIELDS` that differ between two requirement versions.

    Args:
        previous: The version being replaced.
        updated: The new version.

    Returns:
        The names of the changed fields, in declaration order (empty if none).
    """
    return [f for f in REQUIREMENT_CONTENT_FIELDS if getattr(previous, f) != getattr(updated, f)]
