"""
Module: services.artefact_changes

Tells interested modules that an artefact changed, so something that depends on
it can be flagged for a human to re-judge ("Invalidation": detection and notification, not automatic
rewriting). Risk Management uses it to mark a treatment verdict for
reassessment when the requirement that mitigates a risk changes.

Responsibilities:
- `notify_artefact_changed`: hand an `ArtefactChange` to every registered
  module's `on_artefact_changed` hook, inside the caller's transaction.
- `requirement_content_changed`: say whether a new requirement version altered
  what the requirement says (as opposed to its owner, review date or status),
  which is what may invalidate a dependent.

Design decisions:
- A generic hook on `ModuleDefinition`, not an import of any module: core code
  must never name a specific module (CLAUDE.md, Modular Feature System Boundary).
- Hooks run synchronously and must not commit, so a change and the flags it
  raises are one atomic unit. A hook that raises is logged and skipped: a
  dependent's bookkeeping must never fail the edit that triggered it.
- Only changes that can make a dependent wrong raise the hook: content edits and
  archival. Status moves, owner and review-date edits do not, to keep flags rare
  enough to be worth a human's attention.

External dependencies: `app.modules.registry` (the module registry).
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
