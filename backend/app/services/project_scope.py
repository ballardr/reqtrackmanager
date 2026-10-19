"""
Module: services.project_scope

The `?project_scope=` list filter: a project's list widened to its parent and/or child
projects, with the same query parameter on every list endpoint.

Responsibilities:
- Parse the `project_scope` parameter (`ProjectScope`, a FastAPI dependency like
  `services.tags.TagFilter`).
- Resolve the projects a scope covers once per request (`ProjectScope.projects`), reusing
  `services.link_nesting.related_projects` so lists and the link graph apply one rule.
- Fan an endpoint's own single-project list logic out over those projects
  (`ProjectScope.collect`), keeping only what the caller may see there, and label every row
  that comes from another project.
- Say which scope choices a project offers (`scope_options`).

Design decisions:
- Fan-out, not a rewritten query: each endpoint passes a callback that returns its rows for
  one project, so its filters, tag narrowing and row building stay in one place and a new
  filter reaches the widened list for free.
- A project other than the request project contributes only if the caller can open it
  (a genuine role, and a token scoped to one project does not reach its parent or child:
  `link_nesting.can_open_project`), its module and sub-component are enabled *there*, and the
  caller holds the record type's `view` permission *there*. Anything else is omitted, never redacted, so
  a list cannot reveal that a hidden row exists.
- Organisation-owned records (rows whose `project_id` is `None`) come from the request
  project only, exactly as in `services.link_graph.ArtefactResolver`; another project's
  copy of the same organisation list is dropped, so they appear once and unlabelled.
- Archived related projects are left out: their records are history, not live work.
- Project-local filters (a component, a stage, an action type) keep their meaning: a row of
  another project that does not match is simply not in the result.
- Cross-organisation is impossible: the hierarchy stays inside one organisation.

Dependencies: `services.link_nesting`, `services.rbac`, `modules.registry`, `models.project`.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Hashable
from operator import attrgetter
from typing import Literal, TypeVar

from fastapi import Query
from sqlalchemy.orm import Session

from app.models.project import Project
from app.modules.registry import is_module_enabled_for_project, is_module_subcomponent_enabled
from app.schemas.project_scope import ProjectScopeOptionsOut
from app.services.link_nesting import ProjectRelation, RelatedProject, related_projects
from app.services.permissions import encode_permission
from app.services.rbac import get_effective_permissions, permission_satisfied

_Row = TypeVar("_Row")

_PARENT_SCOPES = ("parents", "both")
_CHILD_SCOPES = ("children", "both")


class ProjectScope:
    """The `?project_scope=` list filter, as a FastAPI dependency
    (`project_scope: ProjectScope = Depends()`), so every list endpoint offers the same parameter.

    Attributes:
        name: `this` (default, the request project only), `parents` (it and every ancestor),
            `children` (it and every descendant) or `both`.
    """

    def __init__(
        self,
        project_scope: Literal["this", "parents", "children", "both"] = Query(
            "this",
            description="Widen the list: `parents`, `children` or `both` add the related projects you can open.",
        ),
    ) -> None:
        """Reads the `project_scope` query parameter."""
        self.name = project_scope

    @property
    def widened(self) -> bool:
        """Whether the caller asked for more than the request project."""
        return self.name != "this"

    def projects(self, db: Session, project: Project, user_id: uuid.UUID) -> list[RelatedProject]:
        """The projects this scope covers, request project first, then ancestors nearest
        first, then descendants level by level. Only projects the user can open appear.

        Args:
            db: Active session (read only).
            project: The request project (the caller's access to it is already checked).
            user_id: The caller.
        """
        related, _ = related_projects(db, project, user_id, include_archived=False)
        wanted = {ProjectRelation.SAME}
        if self.name in _PARENT_SCOPES:
            wanted.add(ProjectRelation.ANCESTOR)
        if self.name in _CHILD_SCOPES:
            wanted.add(ProjectRelation.DESCENDANT)
        return [r for r in related if r.relation in wanted]

    def collect(
        self,
        db: Session,
        project: Project,
        user_id: uuid.UUID,
        artefact_type: str,
        rows_for: Callable[[uuid.UUID], list[_Row]],
        *,
        gate: tuple[str, str | None] | None = None,
        id_of: Callable[[_Row], Hashable] = attrgetter("id"),
    ) -> list[_Row]:
        """The request project's rows, plus those of every other project in scope the caller
        may see, each labelled with its project.

        Args:
            db: Active session (read only).
            project: The request project.
            user_id: The caller.
            artefact_type: The listed record type, for the `view` check.
            gate: `(module_key, sub_component_key or None)` the list's own endpoint requires to be
                enabled for a project (the same pair as its `require_project_*_enabled`); `None`
                for a core type, which is never module-gated.
            rows_for: The endpoint's own list logic for one project id, returning the rows the
                response model serialises (its schema derives from `ProjectScopedRow`).
            id_of: Reads a row's identity, unique across the result (default `row.id`).

        Returns:
            Rows grouped by project in `projects()` order, each project's own order kept.
        """
        rows = list(rows_for(project.id))
        if not self.widened:
            return rows
        seen = {id_of(row) for row in rows}
        view = encode_permission(artefact_type, "view")
        for related in self.projects(db, project, user_id):
            if related.relation is ProjectRelation.SAME:
                continue
            other = related.project
            if gate is not None and not _gate_open(db, other.id, gate):
                continue
            if not permission_satisfied(get_effective_permissions(db, user_id, project_id=other.id), view):
                continue
            for row in rows_for(other.id):
                # An organisation-owned record belongs to no project: the request project shows it.
                if getattr(row, "project_id", other.id) is None or id_of(row) in seen:
                    continue
                seen.add(id_of(row))
                # A response row (or an ORM row the response model reads) carries the label fields.
                for field, value in (
                    ("from_project_id", other.id), ("from_project_name", other.name), ("from_project_code", other.code),
                ):
                    setattr(row, field, value)
                rows.append(row)
        return rows


def _gate_open(db: Session, project_id: uuid.UUID, gate: tuple[str, str | None]) -> bool:
    """Whether a list's module (and sub-component, where it names one) is enabled for the project."""
    module_key, sub_key = gate
    if sub_key is None:
        return is_module_enabled_for_project(db, project_id, module_key)
    return is_module_subcomponent_enabled(db, project_id, module_key, sub_key)


def scope_options(db: Session, project: Project, user_id: uuid.UUID) -> ProjectScopeOptionsOut:
    """Which scope choices `project` offers `user_id`: parents and/or children the user can open
    (and, for a scoped token, reach).

    Args:
        db: Active session (read only).
        project: The project being viewed.
        user_id: The viewer.
    """
    related, truncated = related_projects(db, project, user_id, include_archived=False)
    relations = {r.relation for r in related}
    return ProjectScopeOptionsOut(
        has_parents=ProjectRelation.ANCESTOR in relations,
        has_children=ProjectRelation.DESCENDANT in relations,
        truncated=truncated,
    )
