"""
Module: services.definition_suppression

Hide-and-restore of organisation defaults in one project
(`models.definition_suppression.ProjectDefinitionSuppression`), shared by every
vocabulary an organisation defines and a project may take rows from (Pain Point,
Persona, Stakeholder and Risk types).

Responsibilities:
- A registry of vocabulary *kinds*, so a module declares its own kind and the
  table needs no per-module edit.
- Hide, list and restore tombstones; remove them when the org row is deleted.

Design decisions:
- Hiding is per project and not inherited down the project tree: these
  vocabularies already have no ancestor fallback (the organisation list is the
  base every project sees), so a child's view is the organisation list minus its
  own tombstones.
- Hiding stops new use only; records holding the value keep it and still show it.
"""

from __future__ import annotations

import uuid

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.definition_suppression import ProjectDefinitionSuppression

_REGISTERED_KINDS: set[str] = set()


def register_definition_kind(kind: str) -> None:
    """Declares `kind` (e.g. `"pain_point_type"`) as a vocabulary whose
    organisation defaults a project may hide. Idempotent."""
    _REGISTERED_KINDS.add(kind)


def get_registered_definition_kinds() -> frozenset[str]:
    """Every kind registered so far."""
    return frozenset(_REGISTERED_KINDS)


def _require_registered(kind: str) -> None:
    """Raises `ValueError` for a kind nothing registered, so a typo cannot
    create a tombstone nothing reads."""
    if kind not in _REGISTERED_KINDS:
        raise ValueError(f"Unknown definition kind {kind!r}.")


def get_suppressed_ids(db: Session, project_id: uuid.UUID, kind: str) -> set[uuid.UUID]:
    """Ids of the organisation rows of `kind` that `project_id` has hidden."""
    return set(
        db.scalars(
            select(ProjectDefinitionSuppression.org_definition_id).where(
                ProjectDefinitionSuppression.project_id == project_id,
                ProjectDefinitionSuppression.definition_kind == kind,
            )
        ).all()
    )


def hide_definition(db: Session, project_id: uuid.UUID, kind: str, org_definition_id: uuid.UUID) -> bool:
    """Hides an organisation row in a project. Idempotent.

    Returns:
        True if a tombstone was created, False if it was already hidden.

    Raises:
        ValueError: If `kind` is not registered.
    """
    _require_registered(kind)
    if org_definition_id in get_suppressed_ids(db, project_id, kind):
        return False
    db.add(ProjectDefinitionSuppression(project_id=project_id, definition_kind=kind, org_definition_id=org_definition_id))
    db.flush()
    return True


def restore_definitions(
    db: Session, project_id: uuid.UUID, kind: str, org_definition_ids: set[uuid.UUID] | None = None,
) -> set[uuid.UUID]:
    """Removes tombstones so the organisation rows show in the project again.

    Args:
        org_definition_ids: The rows to restore, or `None` for every hidden row
            of `kind`. Ids that are not hidden here are ignored.

    Returns:
        The ids that were restored.

    Raises:
        ValueError: If `kind` is not registered.
    """
    _require_registered(kind)
    hidden = get_suppressed_ids(db, project_id, kind)
    restored = hidden if org_definition_ids is None else hidden & org_definition_ids
    if restored:
        db.execute(
            delete(ProjectDefinitionSuppression).where(
                ProjectDefinitionSuppression.project_id == project_id,
                ProjectDefinitionSuppression.definition_kind == kind,
                ProjectDefinitionSuppression.org_definition_id.in_(restored),
            )
        )
        db.flush()
    return restored


def forget_definition(db: Session, kind: str, org_definition_id: uuid.UUID) -> None:
    """Drops every project's tombstone for an organisation row that is being
    deleted (the table holds no foreign key to it)."""
    db.execute(
        delete(ProjectDefinitionSuppression).where(
            ProjectDefinitionSuppression.definition_kind == kind,
            ProjectDefinitionSuppression.org_definition_id == org_definition_id,
        )
    )
