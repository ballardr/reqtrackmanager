"""
Module: services.link_browse

The scoped finder behind the "Add a link" dialog: find the record a link should
point at by searching, by narrowing step by step, or both.

Responsibilities:
- Search the records a link could point at (`search_link_candidates`): across every
  linkable type (a bounded global search) or within one type, optionally narrowed
  by the options chosen at the type's browse levels.
- Offer the next browse level (`next_browse_step`): its options given the earlier
  choices, or `None` once the chain is complete.
- Declare the browse levels of the two core types (Requirement: Component ->
  Category; Action: Action type); every module declares its own on its
  `ArtefactSummaryProvider.browse_levels`.

Design decisions:
- One authorisation rule for all reads: the page artefact is a visible record of the
  request project, any other project is a related one the caller can open, the type
  is offered there (module enabled) and the caller holds `view` on it *in the searched
  project*. A type or record failing that is simply absent, never an error that
  reveals it.
- Every level is computed server-side from the previous selection only. A selection
  is validated against the options its level would have offered, so a client cannot
  name an option from another organisation or project to widen a later level.
- Global search is bounded: at least `GLOBAL_MIN_QUERY` characters, only types some
  usable link type can reach from this record, `GLOBAL_PER_TYPE` records per type,
  merged to `CANDIDATE_LIMIT`, so one large type cannot crowd out or stall the rest.
- Narrowing defaults to the records' own `facets` (a status, a type); a type with
  too many records to load (Requirement, Compliance requirement) supplies its own
  SQL `filter`.

Dependencies: `services.link_authoring` (authorisation helpers), `services.link_graph`
(visibility), `modules.registry` (providers, levels).
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass

from fastapi import HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.action_type import ActionTypeDefinition
from app.models.enums import ArtefactType
from app.models.project import Project, ProjectCategory, ProjectComponent
from app.models.requirement import Requirement, RequirementVersion
from app.models.requirement_action import RequirementAction
from app.modules.registry import (
    ArtefactSummary,
    BrowseLevel,
    get_all_registered_artefact_types,
    get_artefact_type_label,
    list_artefact_summaries,
)
from app.services.link_authoring import (
    linkable_types_for_project,
    related_project_or_404,
    require_finder_artefact,
    usable_options,
)
from app.services.link_graph import ArtefactResolver

CANDIDATE_LIMIT = 50
GLOBAL_MIN_QUERY = 2
GLOBAL_PER_TYPE = 10
MAX_LEVEL_OPTIONS = 200
# Records an SQL search fetches beyond the limit: one to show the result was cut, one in case the
# page artefact itself (excluded afterwards) is among them.
_SPARE = 2

_REQUIREMENT = ArtefactType.REQUIREMENT.value
_ACTION = ArtefactType.REQUIREMENT_ACTION.value


@dataclass(frozen=True)
class Candidate:
    """A record a link could point at, with its artefact type."""

    type: str
    summary: ArtefactSummary


@dataclass(frozen=True)
class BrowseStep:
    """The next level of a type's browse chain.

    Attributes:
        key / label: The level (`BrowseLevel.key` / `.label`).
        options: `(option id, label)` pairs, at most `MAX_LEVEL_OPTIONS`.
        truncated: Whether more options matched than were returned.
    """

    key: str
    label: str
    options: list[tuple[str, str]]
    truncated: bool


# --- core types' levels ----------------------------------------------------------------------


def _requirement_component_options(
    db: Session, project_id: uuid.UUID, selected: Mapping[str, str], query: str
) -> list[tuple[str, str]]:
    stmt = select(ProjectComponent).where(ProjectComponent.project_id == project_id)
    if query:
        stmt = stmt.where(ProjectComponent.name.ilike(f"%{query}%"))
    return [(str(c.id), c.name) for c in db.scalars(stmt.order_by(ProjectComponent.sort_order, ProjectComponent.name))]


def _requirement_category_options(
    db: Session, project_id: uuid.UUID, selected: Mapping[str, str], query: str
) -> list[tuple[str, str]]:
    component_id = _uuid_or_none(selected.get("component"))
    if component_id is None:
        return []
    stmt = select(ProjectCategory).where(
        ProjectCategory.project_id == project_id, ProjectCategory.component_id == component_id
    )
    if query:
        stmt = stmt.where(ProjectCategory.name.ilike(f"%{query}%"))
    return [(str(c.id), c.name) for c in db.scalars(stmt.order_by(ProjectCategory.sort_order, ProjectCategory.name))]


def _action_type_options(
    db: Session, project_id: uuid.UUID, selected: Mapping[str, str], query: str
) -> list[tuple[str, str]]:
    stmt = (
        select(ActionTypeDefinition).join(RequirementAction, RequirementAction.action_type_id == ActionTypeDefinition.id)
        .where(RequirementAction.project_id == project_id, RequirementAction.is_archived.is_(False)).distinct()
    )
    if query:
        stmt = stmt.where(ActionTypeDefinition.name.ilike(f"%{query}%"))
    return [(str(t.id), t.name) for t in db.scalars(stmt.order_by(ActionTypeDefinition.name))]


_CORE_LEVELS: dict[str, tuple[BrowseLevel, ...]] = {
    _REQUIREMENT: (
        BrowseLevel("component", "Component", _requirement_component_options),
        BrowseLevel("category", "Category", _requirement_category_options),
    ),
    _ACTION: (BrowseLevel("action_type", "Action type", _action_type_options),),
}


def _requirement_candidates(
    db: Session, project_id: uuid.UUID, selected: Mapping[str, str], needle: str, limit: int
) -> list[ArtefactSummary]:
    """Unarchived requirements of the project, narrowed by component/category and by code or name."""
    stmt = (
        select(Requirement, RequirementVersion)
        .join(RequirementVersion, RequirementVersion.requirement_id == Requirement.id)
        .where(
            Requirement.project_id == project_id, Requirement.is_archived.is_(False),
            RequirementVersion.valid_to.is_(None),
        )
    )
    if (component_id := _uuid_or_none(selected.get("component"))) is not None:
        stmt = stmt.where(Requirement.component_id == component_id)
    if (category_id := _uuid_or_none(selected.get("category"))) is not None:
        stmt = stmt.where(Requirement.category_id == category_id)
    if needle:
        like = f"%{needle}%"
        stmt = stmt.where(or_(Requirement.unique_code.ilike(like), RequirementVersion.name.ilike(like)))
    return [
        ArtefactSummary(
            id=r.id, project_id=r.project_id, label=f"{r.unique_code} {v.name}", status=v.status.value,
            is_archived=r.is_archived,
        )
        for r, v in db.execute(stmt.order_by(Requirement.unique_code).limit(limit + _SPARE)).all()
    ]


def _action_candidates(
    db: Session, project_id: uuid.UUID, selected: Mapping[str, str], needle: str, limit: int
) -> list[ArtefactSummary]:
    """Unarchived actions of the project, narrowed by action type and by code or title."""
    stmt = select(RequirementAction).where(
        RequirementAction.project_id == project_id, RequirementAction.is_archived.is_(False)
    )
    if (type_id := _uuid_or_none(selected.get("action_type"))) is not None:
        stmt = stmt.where(RequirementAction.action_type_id == type_id)
    if needle:
        like = f"%{needle}%"
        stmt = stmt.where(or_(RequirementAction.unique_code.ilike(like), RequirementAction.title.ilike(like)))
    return [
        ArtefactSummary(
            id=a.id, project_id=a.project_id, label=f"{a.unique_code} {a.title}", status=a.outcome_status.value,
            is_archived=a.is_archived,
        )
        for a in db.scalars(stmt.order_by(RequirementAction.unique_code).limit(limit + _SPARE)).all()
    ]


def _uuid_or_none(value: str | None) -> uuid.UUID | None:
    if not value:
        return None
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


# --- levels and selections -------------------------------------------------------------------


def levels_for(artefact_type: str) -> tuple[BrowseLevel, ...]:
    """The ordered browse levels of `artefact_type` (core's, else its provider's); empty if none."""
    if artefact_type in _CORE_LEVELS:
        return _CORE_LEVELS[artefact_type]
    from app.modules.registry import get_module_registry

    for definition in get_module_registry().values():
        provider = definition.artefact_summary_providers.get(artefact_type)
        if provider is not None:
            return provider.browse_levels
    return ()


def parse_selected(raw: str | None) -> dict[str, str]:
    """Parses `key:option,key:option` into an ordered mapping.

    Raises:
        HTTPException: 400 when an entry is not `key:option` or a key repeats.
    """
    selected: dict[str, str] = {}
    for part in (raw or "").split(","):
        if not part:
            continue
        key, sep, option = part.partition(":")
        if not sep or not key or not option or key in selected:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid selection.")
        selected[key] = option
    return selected


def _facet_summaries(
    db: Session, project_id: uuid.UUID, other_type: str, selected: Mapping[str, str]
) -> list[ArtefactSummary]:
    """The provider's unarchived records for the project whose facets match every choice in `selected`."""
    return [
        s for s in list_artefact_summaries(db, project_id, other_type)
        if not s.is_archived and all(s.facets.get(key, ("", ""))[0] == option for key, option in selected.items())
    ]


def _level_options(
    db: Session, project_id: uuid.UUID, artefact_type: str, level: BrowseLevel, selected: Mapping[str, str], query: str
) -> list[tuple[str, str]]:
    """Every option of `level` given the earlier choices and the label text `query`."""
    if level.list_options is not None:
        return level.list_options(db, project_id, selected, query)
    needle = query.lower()
    seen: dict[str, str] = {}
    for summary in _facet_summaries(db, project_id, artefact_type, selected):
        facet = summary.facets.get(level.key)
        if facet is not None and (not needle or needle in facet[1].lower()):
            seen.setdefault(facet[0], facet[1])
    return sorted(seen.items(), key=lambda item: item[1].lower())


def _validated_selection(
    db: Session, project_id: uuid.UUID, artefact_type: str, selected: Mapping[str, str]
) -> dict[str, str]:
    """`selected` checked to be a prefix of the type's levels, each option one its level offered.

    Raises:
        HTTPException: 400 when a key is not the next level in order or an option was not
            offered given the choices before it (so a client cannot widen a level by naming
            an option from elsewhere).
    """
    levels = levels_for(artefact_type)
    valid: dict[str, str] = {}
    for index, (key, option) in enumerate(selected.items()):
        if index >= len(levels) or levels[index].key != key:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid selection.")
        offered = {value for value, _ in _level_options(db, project_id, artefact_type, levels[index], valid, "")}
        if option not in offered:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid selection.")
        valid[key] = option
    return valid


# --- authorisation shared by the reads -------------------------------------------------------


@dataclass(frozen=True)
class _Scope:
    """What a finder read is allowed to search: the searched project and the resolver for it."""

    project: Project
    searched: Project
    resolver: ArtefactResolver


def _authorise(
    db: Session, *, project: Project, user_id: uuid.UUID, artefact_type: str, artefact_id: uuid.UUID,
    other_project_id: uuid.UUID | None,
) -> _Scope:
    """The page artefact is visible and the searched project is the request project or a related one.

    Raises:
        HTTPException: 404 the artefact is not a visible record of the project or
            `other_project_id` is not a related project the caller can open.
    """
    page_resolver = ArtefactResolver(db, project, user_id)
    require_finder_artefact(db, page_resolver, project, artefact_type, artefact_id)
    searched = project
    if other_project_id is not None and other_project_id != project.id:
        searched = related_project_or_404(db, project, user_id, other_project_id)
    resolver = page_resolver if searched is project else ArtefactResolver(db, searched, user_id)
    return _Scope(project=project, searched=searched, resolver=resolver)


def _type_searchable(db: Session, scope: _Scope, other_type: str) -> bool:
    """Whether `other_type` is registered, offered in the searched project and viewable there."""
    return (
        other_type in get_all_registered_artefact_types()
        and other_type in linkable_types_for_project(db, scope.searched)
        and scope.resolver.holds(other_type, "view")
    )


# --- reads -----------------------------------------------------------------------------------


def next_browse_step(
    db: Session,
    *,
    project: Project,
    user_id: uuid.UUID,
    artefact_type: str,
    artefact_id: uuid.UUID,
    other_type: str,
    other_project_id: uuid.UUID | None = None,
    selected: Mapping[str, str] | None = None,
    query: str = "",
) -> BrowseStep | None:
    """The next browse level of `other_type` given the options already chosen.

    Args:
        db: Active session (read only).
        project: The project the request is scoped to (membership already checked).
        user_id: The acting user.
        artefact_type / artefact_id: The page artefact.
        other_type: The artefact type being browsed.
        other_project_id: An ancestor or descendant project to browse instead.
        selected: `{level key: option id}` chosen so far, in level order.
        query: Text the options' labels must contain.

    Returns:
        The next level with its options (capped), or `None` when every level has been
        chosen, the type has none, or the type is not offered or viewable in the searched
        project.

    Raises:
        HTTPException: 404 the page artefact is not visible, `other_type` is unregistered,
            or `other_project_id` is not a related project the caller can open; 400 an
            invalid selection.
    """
    scope = _authorise(
        db, project=project, user_id=user_id, artefact_type=artefact_type, artefact_id=artefact_id,
        other_project_id=other_project_id,
    )
    if other_type not in get_all_registered_artefact_types():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Linked record type not found.")
    if not _type_searchable(db, scope, other_type):
        return None
    chosen = _validated_selection(db, scope.searched.id, other_type, selected or {})
    levels = levels_for(other_type)
    if len(chosen) >= len(levels):
        return None
    level = levels[len(chosen)]
    options = _level_options(db, scope.searched.id, other_type, level, chosen, query.strip())
    return BrowseStep(
        key=level.key, label=level.label, options=options[:MAX_LEVEL_OPTIONS], truncated=len(options) > MAX_LEVEL_OPTIONS
    )


def _records_of_type(
    db: Session, scope: _Scope, other_type: str, selected: Mapping[str, str], needle: str, limit: int
) -> list[ArtefactSummary]:
    """Up to `limit` + `_SPARE` unarchived records of `other_type` in the searched project matching the scope."""
    searched = scope.searched
    if other_type == _REQUIREMENT:
        return _requirement_candidates(db, searched.id, selected, needle, limit)
    if other_type == _ACTION:
        return _action_candidates(db, searched.id, selected, needle, limit)
    from app.modules.registry import get_module_registry

    provider = next(
        (d.artefact_summary_providers[other_type] for d in get_module_registry().values()
         if other_type in d.artefact_summary_providers), None,
    )
    if provider is not None and provider.filter is not None:
        rows = provider.filter(db, searched.id, selected, needle, limit)
    else:
        rows = [
            s for s in _facet_summaries(db, searched.id, other_type, selected)
            if not needle or needle in s.label.lower()
        ]
        rows.sort(key=lambda s: s.label.lower())
    # An organisation-owned record is only ever offered from the request project.
    return [s for s in rows if s.project_id == searched.id or (s.project_id is None and searched is scope.project)]


def search_link_candidates(
    db: Session,
    *,
    project: Project,
    user_id: uuid.UUID,
    artefact_type: str,
    artefact_id: uuid.UUID,
    other_type: str | None = None,
    other_project_id: uuid.UUID | None = None,
    selected: Mapping[str, str] | None = None,
    query: str | None = None,
    limit: int = CANDIDATE_LIMIT,
) -> tuple[list[Candidate], bool]:
    """The records the page artefact could be linked to.

    With `other_type` the search is within that type, narrowed by `selected`. Without it
    the search spans every type some usable link type can reach from this record, needs at
    least `GLOBAL_MIN_QUERY` characters of `query`, and takes at most `GLOBAL_PER_TYPE`
    from each type before merging.

    Args:
        db: Active session (read only).
        project: The project the request is scoped to (membership already checked).
        user_id: The acting user.
        artefact_type / artefact_id: The page artefact (excluded from the result).
        other_type: The artefact type to search; `None` searches every linkable type.
        other_project_id: An ancestor or descendant project to search instead of `project`.
        selected: `{level key: option id}` narrowing one type; ignored by the global search.
        query: Case-insensitive text matched against the record's label.
        limit: Maximum records returned.

    Returns:
        `(records, truncated)`: unarchived records the user holds `view` on in the searched
        project whose module is enabled there, ordered by label; empty (not an error) when
        a type is not offered there or a global query is too short.

    Raises:
        HTTPException: 404 the page artefact is not visible, `other_type` is unregistered,
            or `other_project_id` is not a related project the caller can open; 400 an
            invalid selection.
    """
    scope = _authorise(
        db, project=project, user_id=user_id, artefact_type=artefact_type, artefact_id=artefact_id,
        other_project_id=other_project_id,
    )
    needle = (query or "").strip().lower()
    if other_type is not None:
        if other_type not in get_all_registered_artefact_types():
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Linked record type not found.")
        chosen = _validated_selection(db, scope.searched.id, other_type, selected or {}) if selected else {}
        if not _type_searchable(db, scope, other_type):
            return [], False
        rows = _records_of_type(db, scope, other_type, chosen, needle, limit)
        rows = [s for s in rows if (other_type, s.id) != (artefact_type, artefact_id)]
        rows.sort(key=lambda s: s.label.lower())
        return [Candidate(other_type, s) for s in rows[:limit]], len(rows) > limit

    if len(needle) < GLOBAL_MIN_QUERY:
        return [], False
    other_project = scope.searched if scope.searched is not project else None
    reachable = {
        t for option in usable_options(db, project, artefact_type, None, other_project) for t in option.other_types
    }
    merged: list[Candidate] = []
    truncated = False
    for candidate_type in sorted(reachable, key=lambda t: get_artefact_type_label(t).lower()):
        if not _type_searchable(db, scope, candidate_type):
            continue
        rows = _records_of_type(db, scope, candidate_type, {}, needle, GLOBAL_PER_TYPE)
        rows = [s for s in rows if (candidate_type, s.id) != (artefact_type, artefact_id)]
        rows.sort(key=lambda s: s.label.lower())
        truncated = truncated or len(rows) > GLOBAL_PER_TYPE
        merged.extend(Candidate(candidate_type, s) for s in rows[:GLOBAL_PER_TYPE])
    merged.sort(key=lambda c: (c.summary.label.lower(), c.type))
    return merged[:limit], truncated or len(merged) > limit
