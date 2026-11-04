"""
Module: services.report_snippet_scope

Which saved report snippets a scope can see, and hiding or restoring the inherited ones.

Responsibilities:
- `resolve_project_snippets`: the saved snippets a project can reach, each with where it comes from.
- `hide_snippet` / `restore_snippets`: a project hides an inherited snippet and brings it back.
- `list_org_snippets`: an organisation's own saved snippets.

Design decisions:
- **Visibility is additive, as for layouts and packs.** A project sees its own snippets, its ancestors' (nearest first) and
  the organisation's, de-duplicated by name (case-insensitively) with the nearest owner winning. The Action Types rule
  ("own rows, else the nearest ancestor's") would hide every inherited snippet the moment a project saved one of its own.
- **Hiding is a tombstone** (`ProjectDefinitionSuppression`, kind `report_snippet`), per project and not inherited
  downwards. Only an inherited snippet can be hidden; a project removes its own by deleting it. A hidden snippet keeps its
  name, so it does not let a farther snippet of the same name show through.

Dependencies: `models.report_snippet`, `services.project_hierarchy`, `services.definition_suppression`.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.project import Project
from app.models.report_snippet import SavedReportSnippet
from app.services import definition_suppression
from app.services.audit import log_event
from app.services.project_hierarchy import get_project_chain_ids

SNIPPET_KIND = "report_snippet"
"""The `ProjectDefinitionSuppression.definition_kind` of a hidden saved snippet."""

definition_suppression.register_definition_kind(SNIPPET_KIND)

Origin = Literal["organization", "ancestor", "project"]


@dataclass(frozen=True)
class ScopedSnippet:
    """A saved snippet as one project sees it.

    Attributes:
        snippet: The snippet row.
        origin: `project` (its own), `ancestor` (a parent project's) or `organization`.
        hidden: Whether this project has hidden it (never true for its own).
    """

    snippet: SavedReportSnippet
    origin: Origin
    hidden: bool


def list_org_snippets(db: Session, organization_id: uuid.UUID) -> list[SavedReportSnippet]:
    """The organisation-level saved snippets of `organization_id`, by name."""
    return list(db.scalars(
        select(SavedReportSnippet)
        .where(SavedReportSnippet.organization_id == organization_id, SavedReportSnippet.project_id.is_(None))
        .order_by(SavedReportSnippet.name)
    ).all())


def resolve_project_snippets(db: Session, project: Project) -> list[ScopedSnippet]:
    """Every saved snippet `project` can reach, nearest owner first, hidden ones flagged.

    Args:
        db: Active session.
        project: The project.

    Returns:
        The de-duplicated snippets: the project's own, then each ancestor's (nearest first), then the organisation's;
        within a tier by name. A farther snippet whose name a nearer one already uses is left out.
    """
    chain = get_project_chain_ids(db, project.id)  # the project itself first, then its parent ... the root
    rows = list(db.scalars(
        select(SavedReportSnippet).where(
            SavedReportSnippet.organization_id == project.organization_id,
            (SavedReportSnippet.project_id.in_(chain)) | (SavedReportSnippet.project_id.is_(None)),
        )
    ).all())
    rank = {pid: i for i, pid in enumerate(chain)}
    rows.sort(key=lambda r: (rank.get(r.project_id, len(chain)) if r.project_id else len(chain), r.name.lower()))
    hidden_ids = definition_suppression.get_suppressed_ids(db, project.id, SNIPPET_KIND)
    seen: set[str] = set()
    out: list[ScopedSnippet] = []
    for row in rows:
        key = row.name.strip().lower()
        if key in seen:
            continue
        seen.add(key)
        origin: Origin = "organization" if row.project_id is None else ("project" if row.project_id == project.id else "ancestor")
        out.append(ScopedSnippet(row, origin, hidden=origin != "project" and row.id in hidden_ids))
    return out


def reachable_snippet(db: Session, project: Project, snippet_id: uuid.UUID) -> ScopedSnippet | None:
    """`snippet_id` as `project` sees it, or `None` when it is not reachable (another owner's, or shadowed)."""
    return next((s for s in resolve_project_snippets(db, project) if s.snippet.id == snippet_id), None)


def hide_snippet(db: Session, project: Project, snippet_id: uuid.UUID, *, actor_id: uuid.UUID | None) -> bool:
    """Hides an inherited saved snippet in `project`. Idempotent.

    Raises:
        LookupError: The snippet is not one the project inherits (unreachable, shadowed, or its own).
    """
    scoped = reachable_snippet(db, project, snippet_id)
    if scoped is None or scoped.origin == "project":
        raise LookupError("No such inherited snippet.")
    created = definition_suppression.hide_definition(db, project.id, SNIPPET_KIND, snippet_id)
    if created:
        log_event(
            db, entity_type="report_snippet", entity_id=snippet_id, action="hidden", actor_id=actor_id,
            organization_id=project.organization_id, project_id=project.id, detail={},
        )
    return created


def restore_snippets(
    db: Session, project: Project, snippet_ids: set[uuid.UUID] | None, *, actor_id: uuid.UUID | None,
) -> set[uuid.UUID]:
    """Shows hidden saved snippets in `project` again.

    Args:
        snippet_ids: The snippets to restore, or `None` for every hidden one.

    Returns:
        The ids restored.
    """
    restored = definition_suppression.restore_definitions(db, project.id, SNIPPET_KIND, snippet_ids)
    for snippet_id in sorted(restored, key=str):
        log_event(
            db, entity_type="report_snippet", entity_id=snippet_id, action="restored", actor_id=actor_id,
            organization_id=project.organization_id, project_id=project.id, detail={},
        )
    return restored


__all__ = [
    "SNIPPET_KIND", "Origin", "ScopedSnippet", "hide_snippet", "list_org_snippets", "reachable_snippet",
    "resolve_project_snippets", "restore_snippets",
]
