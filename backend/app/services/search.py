"""
Module: services.search

The global search: one query across every record type the caller may see, in one project,
every project they can open, or a module-defined unit (a Compliance standard).

Responsibilities:
- Resolve the scope to the projects searched (`_resolve_scope`), keep the ones the caller can
  open, and work out per record type the projects where the type is offered (module and
  sub-component enabled) and viewable (`view` permission) (`_authorised_projects`).
- Build one SQL query per record type from its `ArtefactSearchProvider` (scope, text match,
  filters, relevance tier), run it, and merge, rank and page the results (`run_search`).
- Resolve the fields searched (request, else the user's `search_default_fields`, else ID, Title
  and Tags) and list the fields the caller can choose from (`available_fields`).
- Shape each hit: code, title, status label, owning project, snippet of the first matching
  field, and the record to open.

Design decisions:
- Authorisation is applied before querying and results are omitted, never redacted, so a type
  count never discloses a record the caller cannot open. A project is searched only if the
  caller holds a genuine role there (and, for a token, may reach it); a type only where its
  module is enabled and `view` is held *in that project*. The same rules as the link finder
  and the project-scope lists.
- Query-time search per type, not a central index: a second copy of every record's text would
  have to follow erasure, hard delete, per-project hiding and permission changes. Bounds keep it
  cheap: a minimum query length, a per-type row cap of `offset + limit`, a depth limit of
  `MAX_DEPTH`, a project cap, and a per-search `statement_timeout`.
- Fields are opt-in per provider; ID (the record's code, qualified or not), Title and Tags are
  built here, so every taggable type is searched on tags with no provider work.
- A record owned by the organisation (a shared persona) is found only through a project that is
  allowed to see it, using the owning module's `get_many_in_project` rule (per-project hiding),
  and its count is taken after that check.
- The query text is never logged, audited or traced: the log line carries the scope, field keys,
  match mode, result count and duration only.

Dependencies: `modules.registry` (providers, scopes, enablement), `services.rbac`
(permissions, memoised role lookups), `services.project_access`, `models.tag`.
"""

from __future__ import annotations

import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from fastapi import HTTPException, status
from sqlalchemy import String, and_, case, cast, exists, func, literal, or_, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.models.organization import Organization, UserOrgRole
from app.models.project import Project
from app.models.tag import ArtefactTag, Tag
from app.models.user import User
from app.modules.registry import (
    ArtefactSearchProvider,
    ScopeResolution,
    artefact_type_enabled_for_project,
    artefact_type_module,
    get_artefact_summaries_in_project,
    get_artefact_type_label,
    get_search_providers,
    get_search_scopes,
    is_module_enabled_for_project,
    is_org_module_subcomponent_enabled,
    memoize_module_state,
    prefetch_project_module_state,
)
from app.services.permissions import encode_permission
from app.services.project_access import accessible_project_ids
from app.services.rbac import (
    get_effective_org_roles,
    get_effective_permissions,
    memoize_user_lookups,
    permission_satisfied,
    prefetch_project_roles,
    session_may_reach_project,
)

logger = logging.getLogger(__name__)

MIN_QUERY = 2
MAX_QUERY = 200
MAX_TERMS = 8
MAX_FIELD_KEYS = 60
#: Deepest result a search will page to; a deeper page asks the person to refine.
MAX_DEPTH = 500
#: Most projects one search covers; a user with more is told the search was cut.
MAX_SEARCH_PROJECTS = 250
STATEMENT_TIMEOUT_MS = 5000
#: Most hit rows fetched for a type that can be organisation-owned (visibility is checked per row).
_ORG_OWNED_FETCH = MAX_DEPTH + 1
#: Most projects asked about one organisation-owned record's visibility.
_ORG_VISIBILITY_PROJECT_CAP = 25
_SNIPPET_BEFORE = 60
_SNIPPET_AFTER = 100
PROJECT_TYPE = "project"

DEFAULT_FIELDS = ("id", "title", "tags")
_RESERVED_FIELDS = {"id": "ID", "title": "Title", "tags": "Tags"}
#: The reserved key for a record's comments: available only to the types that declare a comment table, and
#: only ever chosen for one search, never a default (an `EXISTS` over a table per type is much dearer than
#: matching the record's own columns).
COMMENTS_FIELD = "comments"
_COMMENTS_LABEL = "Comments"
#: The `ui_preferences` key holding a user's default search fields.
SEARCH_DEFAULT_FIELDS_KEY = "search_default_fields"
#: The `ui_preferences` key holding whether a project search also covers organisation-level records (default on).
SEARCH_INCLUDE_ORG_RECORDS_KEY = "search_include_org_records"

Scope = Literal["project", "all"] | str
Match = Literal["contains", "phrase"]
Sort = Literal["relevance", "updated"]


class SearchTimeout(Exception):
    """The search ran past `STATEMENT_TIMEOUT_MS`; the caller should narrow it."""


@dataclass
class SearchParams:
    """One search request, already validated for shape.

    Attributes:
        q: The text searched for.
        scope: `"project"`, `"all"`, or `"<module key>:<scope key>:<ref id>"`.
        project_id: The project for `scope="project"`.
        organization_ids / project_ids: Narrow the projects searched.
        types: Narrow to these record types (`"project"` is a type); `None` for all.
        statuses: Narrow to these status values.
        fields: Field keys to match; `None` uses the user's default.
        match: `"contains"` (every word, any order) or `"phrase"`.
        include_archived: Whether archived records are included.
        updated_from / updated_to: Bounds on the record's last change (UTC instants).
        sort: `"relevance"` or `"updated"`.
        include_organization_records: Whether a project search also covers its organisation's records; `None`
            uses the preference (default on). The all-projects scope always includes them.
        limit / offset: The page.
        counts: Whether to compute per-type counts and the total (skipped for the live dropdown).
    """

    q: str
    scope: Scope = "all"
    project_id: uuid.UUID | None = None
    organization_ids: list[uuid.UUID] | None = None
    project_ids: list[uuid.UUID] | None = None
    types: list[str] | None = None
    statuses: list[str] | None = None
    fields: list[str] | None = None
    match: Match = "contains"
    include_archived: bool = False
    updated_from: datetime | None = None
    updated_to: datetime | None = None
    sort: Sort = "relevance"
    #: Whether a search of one project also covers the organisation-level records of its organisation
    #: (a shared Strategy); `None` uses the person's preference, on unless they turned it off.
    include_organization_records: bool | None = None
    limit: int = 25
    offset: int = 0
    counts: bool = True


@dataclass
class Snippet:
    """The first matching field of a hit, windowed around the match."""

    field_key: str
    field_label: str
    text: str
    ranges: list[tuple[int, int]]


@dataclass
class SearchHit:
    """One result."""

    type: str
    type_label: str
    id: uuid.UUID
    code: str
    title: str
    status: str | None
    status_label: str | None
    is_archived: bool
    updated_at: datetime | None
    project_id: uuid.UUID | None
    project_name: str | None
    project_code: str | None
    organization_id: uuid.UUID | None
    organization_code: str | None
    open_type: str
    open_id: uuid.UUID
    open_project_id: uuid.UUID | None
    snippet: Snippet | None = None
    tier: int = 3


@dataclass
class TypeCount:
    """How many records of a type matched."""

    type: str
    label: str
    count: int
    capped: bool


@dataclass
class SearchResult:
    """What a search found.

    Attributes:
        hits: The requested page.
        total: Matches across the selected types, capped at `MAX_DEPTH` (`total_capped`); `None`
            when counts were not asked for.
        type_counts: Matches per type before the type filter (for the filter's counts).
        fields_used: The field keys matched.
        not_searched: Types left out because they declare none of the selected fields.
        statuses: The status values and labels of the types searched, for the status filter.
        organizations: The caller's organisations, for the organisation filter.
        projects_truncated: The caller can open more projects than one search covers.
    """

    hits: list[SearchHit]
    total: int | None
    total_capped: bool
    type_counts: list[TypeCount]
    fields_used: list[str]
    not_searched: list[tuple[str, str]]
    statuses: list[tuple[str, str]]
    organizations: list[tuple[uuid.UUID, str, str]]
    projects_truncated: bool = False


@dataclass
class _Context:
    """The authorised world of one search."""

    projects: dict[uuid.UUID, Project]
    allowed: dict[str, list[uuid.UUID]]
    restrictions: dict[str, Any] | None
    organizations: dict[uuid.UUID, Organization]
    truncated: bool = False
    types: list[str] = field(default_factory=list)
    #: Per type with an organisation-level surface, the organisations whose members may search it.
    org_allowed: dict[str, list[uuid.UUID]] = field(default_factory=dict)

    @property
    def searchable_types(self) -> list[str]:
        """Every record type the caller may search anywhere in this scope."""
        return list(dict.fromkeys([*self.allowed, *self.org_allowed]))


# --- scope and authorisation -----------------------------------------------------------------


def _not_found() -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, "Search scope not found.")


def _openable(db: Session, user_id: uuid.UUID, project_ids: set[uuid.UUID]) -> set[uuid.UUID]:
    """The projects among `project_ids` the caller holds a genuine role in and the credential may reach."""
    openable = accessible_project_ids(db, user_id) & project_ids
    return {pid for pid in openable if session_may_reach_project(db, pid)}


def _resolve_scope(db: Session, user: User, params: SearchParams) -> tuple[set[uuid.UUID], dict[str, Any] | None]:
    """The candidate project ids and per-type restrictions for the requested scope.

    Raises:
        HTTPException: 404 when the scope's project or unit does not exist or the caller cannot reach it.
    """
    scope = params.scope
    if scope == "project":
        if params.project_id is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "A project is required to search one project.")
        openable = _openable(db, user.id, {params.project_id})
        if not openable:
            raise _not_found()
        return openable, None
    if scope == "all":
        candidates = set(
            db.scalars(
                select(Project.id)
                .join(Organization, Organization.id == Project.organization_id)
                .where(Project.id.in_(accessible_project_ids(db, user.id)), Project.is_archived.is_(False), Organization.is_active.is_(True))
            ).all()
        )
        return {pid for pid in candidates if session_may_reach_project(db, pid)}, None
    parts = scope.split(":", 2)
    if len(parts) != 3:
        raise _not_found()
    module_key, scope_key, ref = parts
    registered = get_search_scopes().get(f"{module_key}:{scope_key}")
    try:
        ref_id = uuid.UUID(ref)
    except ValueError:
        raise _not_found() from None
    if registered is None:
        raise _not_found()
    _definition, search_scope = registered
    resolution: ScopeResolution | None = search_scope.resolve(db, user.id, ref_id)
    if resolution is None:
        raise _not_found()
    candidates = {pid for pid in _openable(db, user.id, set(resolution.project_ids)) if is_module_enabled_for_project(db, pid, module_key)}
    if not candidates:
        raise _not_found()
    return candidates, dict(resolution.restrictions)


def _authorised_projects(db: Session, user: User, params: SearchParams) -> _Context:
    """Resolves the scope, applies the organisation/project filters and works out, per record
    type, the projects where the caller may search it.

    Args:
        db: Active session (read only).
        user: The caller.
        params: The request.
    """
    candidates, restrictions = _resolve_scope(db, user, params)
    if params.project_ids is not None:
        candidates &= set(params.project_ids)
    projects = {p.id: p for p in db.scalars(select(Project).where(Project.id.in_(candidates)).order_by(Project.name, Project.id)).all()}
    if params.organization_ids is not None:
        wanted_orgs = set(params.organization_ids)
        projects = {pid: p for pid, p in projects.items() if p.organization_id in wanted_orgs}
    # An organisation that requires two-factor authentication locks out a member without it, from every
    # project and organisation read (`rbac._require_org_2fa`); a search must not be the way round that.
    locked_orgs = {
        o.id for o in db.scalars(select(Organization).where(Organization.require_2fa.is_(True))).all()
    } if not user.is_2fa_enabled else set()
    if locked_orgs:
        projects = {pid: p for pid, p in projects.items() if p.organization_id not in locked_orgs}
    truncated = len(projects) > MAX_SEARCH_PROJECTS
    if truncated:
        projects = dict(list(projects.items())[:MAX_SEARCH_PROJECTS])
    prefetch_project_roles(db, user.id, projects.keys())
    prefetch_project_module_state(db, projects.keys())
    held = {pid: get_effective_permissions(db, user.id, project_id=pid) for pid in projects}
    providers = get_search_providers()
    allowed: dict[str, list[uuid.UUID]] = {}
    for artefact_type in providers:
        if restrictions is not None and artefact_type not in restrictions:
            continue
        view = encode_permission(artefact_type, "view")
        ok = [
            pid for pid in projects
            if permission_satisfied(held[pid], view) and artefact_type_enabled_for_project(db, artefact_type, pid)
        ]
        if ok:
            allowed[artefact_type] = ok
    org_allowed = _organisation_surfaces(db, user, params, restrictions, locked_orgs, providers, projects)
    wanted_orgs = {p.organization_id for p in projects.values()} | {o for orgs in org_allowed.values() for o in orgs}
    organizations = {o.id: o for o in db.scalars(select(Organization).where(Organization.id.in_(wanted_orgs))).all()}
    return _Context(
        projects=projects, allowed=allowed, restrictions=restrictions, organizations=organizations, truncated=truncated,
        org_allowed=org_allowed,
    )


def _organisation_surfaces(
    db: Session, user: User, params: SearchParams, restrictions: dict[str, Any] | None, locked_orgs: set[uuid.UUID],
    providers: dict[str, ArtefactSearchProvider], projects: dict[uuid.UUID, Project],
) -> dict[str, list[uuid.UUID]]:
    """Per type with an organisation-level surface, the organisations whose records may be searched.

    The all-projects scope covers every organisation the caller belongs to. A search of one project covers that
    project's organisation (unless the person turned that off, see `include_organization_records`) and only for a
    type its module has switched on in that project: an organisation record is relevant to the project unless
    the project has the feature off. A module's unit never does, and a credential bound to one project never
    reaches them. Each organisation must be active, not locked by its two-factor rule, within a token's
    organisation scope, and the caller a member where the owning module's sub-component is on: the rule the
    organisation-level list applies.
    """
    surfaces = [(t, p) for t, p in providers.items() if p.organization_subcomponent]
    if restrictions is not None or not surfaces or "module_frame_project_id" in db.info or params.scope not in ("all", "project"):
        return {}
    if params.scope == "project" and not _includes_organization_records(user, params):
        return {}
    allowed_orgs = db.info.get("pat_allowed_org_ids")
    wanted = set(params.organization_ids) if params.organization_ids is not None else None
    project_orgs = {p.organization_id for p in projects.values()} if params.scope == "project" else None
    result: dict[str, list[uuid.UUID]] = {}
    for org_id, _name, _code in _user_organizations(db, user.id):
        if org_id in locked_orgs or (allowed_orgs is not None and org_id not in allowed_orgs) or (wanted is not None and org_id not in wanted):
            continue
        if project_orgs is not None and org_id not in project_orgs:
            continue
        if not get_effective_org_roles(db, user.id, org_id):
            continue
        for artefact_type, provider in surfaces:
            module = artefact_type_module(artefact_type)
            if module is None or not is_org_module_subcomponent_enabled(db, org_id, module.key, provider.organization_subcomponent):
                continue
            if params.scope == "project" and not any(
                artefact_type_enabled_for_project(db, artefact_type, pid) for pid, p in projects.items() if p.organization_id == org_id
            ):
                continue
            result.setdefault(artefact_type, []).append(org_id)
    return result


def _includes_organization_records(user: User, params: SearchParams) -> bool:
    """Whether a project search covers organisation-level records: the request, else the preference, else yes."""
    if params.include_organization_records is not None:
        return params.include_organization_records
    stored = (user.ui_preferences or {}).get(SEARCH_INCLUDE_ORG_RECORDS_KEY)
    return stored if isinstance(stored, bool) else True


def _user_organizations(db: Session, user_id: uuid.UUID) -> list[tuple[uuid.UUID, str, str]]:
    """`(id, name, code)` of the active organisations the user belongs to, by name."""
    rows = db.execute(
        select(Organization.id, Organization.name, Organization.code)
        .join(UserOrgRole, UserOrgRole.organization_id == Organization.id)
        .where(UserOrgRole.user_id == user_id, Organization.is_active.is_(True))
        .group_by(Organization.id)
        .order_by(Organization.name)
    ).all()
    return [(r[0], r[1], r[2]) for r in rows]


# --- fields ----------------------------------------------------------------------------------


def _preferred_fields(user: User) -> list[str] | None:
    """The user's stored default fields, if any."""
    stored = (user.ui_preferences or {}).get(SEARCH_DEFAULT_FIELDS_KEY)
    return [str(k) for k in stored] if isinstance(stored, list) and stored else None


def _field_labels(types: list[str]) -> dict[str, tuple[str, list[str]]]:
    """`{key: (label, [type labels that carry it])}` for the given types, reserved fields first."""
    providers = get_search_providers()
    merged: dict[str, tuple[str, list[str]]] = {
        key: (label, [get_artefact_type_label(t) for t in types]) for key, label in _RESERVED_FIELDS.items()
    }
    commenting = [get_artefact_type_label(t) for t in types if providers[t].comments is not None]
    for artefact_type in types:
        for f in providers[artefact_type].fields:
            if f.key in _RESERVED_FIELDS:
                continue
            label, carriers = merged.setdefault(f.key, (f.label, []))
            carriers.append(get_artefact_type_label(artefact_type))
    if commenting:
        merged[COMMENTS_FIELD] = (_COMMENTS_LABEL, commenting)
    return merged


def resolve_fields(user: User, requested: list[str] | None, offered: set[str]) -> list[str]:
    """The field keys a search matches: the request, else the user's default, else ID, Title and Tags.

    Keys that are not offered (a module off, a renamed field) are ignored rather than failing the
    search; `id` and `title` are always included.

    Args:
        user: The caller (for the stored default).
        requested: Field keys from the request, if any.
        offered: The keys the caller can choose from.
    """
    # A request may ask for comments; a stored default never carries them.
    chosen = requested if requested else [k for k in (_preferred_fields(user) or DEFAULT_FIELDS) if k != COMMENTS_FIELD]
    fields = [k for k in dict.fromkeys(chosen) if k in offered]
    for required in ("title", "id"):
        if required not in fields:
            fields.insert(0, required)
    return fields


def available_fields(db: Session, user: User) -> list[tuple[str, str, list[str]]]:
    """The fields the caller can choose from: those of the record types they can view in at least
    one project they can open, merged by key.

    Returns:
        `(key, label, type labels)` triples, ID, Title and Tags first, the rest by label.
    """
    with memoize_user_lookups(), memoize_module_state():
        context = _authorised_projects(db, user, SearchParams(q="", scope="all"))
    types = sorted(context.searchable_types, key=lambda t: get_artefact_type_label(t).lower())
    merged = _field_labels(types)
    ordered = [(k, *merged[k]) for k in _RESERVED_FIELDS]
    ordered += sorted(((k, *v) for k, v in merged.items() if k not in _RESERVED_FIELDS), key=lambda f: f[1].lower())
    return ordered


def validate_default_fields(db: Session, user: User, value: object) -> list[str]:
    """Checks a `search_default_fields` preference before it is stored and returns it normalised.

    `id` and `title` are always first (a search that cannot match a code or title would surprise
    people); every other key must be one the caller can currently choose.

    Args:
        db: Active session (read only).
        user: The caller.
        value: The submitted preference.

    Raises:
        HTTPException: 422 when it is not a list of known field keys.
    """
    if not isinstance(value, list) or not all(isinstance(k, str) for k in value) or len(value) > MAX_FIELD_KEYS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Default search fields must be a list of field keys.")
    if COMMENTS_FIELD in value:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Comments can be searched for one search at a time, not saved as a default."
        )
    offered = {key for key, _label, _types in available_fields(db, user)}
    unknown = sorted({k for k in value if k not in offered})
    if unknown:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Unknown search fields: {', '.join(unknown)}.")
    return ["id", "title", *[k for k in dict.fromkeys(value) if k not in ("id", "title")]]


# --- query building --------------------------------------------------------------------------


def _escape_like(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _like(column: Any, term: str) -> Any:
    return cast(column, String).ilike(f"%{_escape_like(term)}%", escape="\\")


def _terms(params: SearchParams) -> list[str]:
    """The lower-cased terms to match: each word (all must match) or the whole phrase."""
    text_ = " ".join(params.q.split()).lower()
    if params.match == "phrase":
        return [text_]
    return text_.split(" ")[:MAX_TERMS]


def _tag_exists(artefact_type: str, id_column: Any, term: str) -> Any:
    """Whether the record carries a tag whose name contains `term` (case-folded `name_key`)."""
    return exists(
        select(1)
        .select_from(ArtefactTag.__table__.join(Tag.__table__, Tag.id == ArtefactTag.tag_id))
        .where(
            ArtefactTag.artefact_type == artefact_type,
            ArtefactTag.artefact_id == id_column,
            Tag.name_key.like(f"%{_escape_like(term)}%", escape="\\"),
        )
    )


def _comment_exists(comments: Any, id_column: Any, term: str) -> Any:
    """Whether the record has a comment whose text contains `term`."""
    return exists(
        select(1).select_from(comments.model).where(comments.record_id == id_column, *comments.where, _like(comments.body, term))
    )


def _qualified_code_match(provider: ArtefactSearchProvider, term: str, context: _Context, *, exact: bool) -> Any | None:
    """`PROJECT-REQ-001` style match: the code after the first hyphen, owned by the project (or
    organisation) whose code precedes it. `None` when no searched project or organisation has that code."""
    if "-" not in term:
        return None
    prefix, rest = term.split("-", 1)
    if not prefix or not rest:
        return None
    columns = provider.columns
    project_ids = [pid for pid, p in context.projects.items() if p.code.lower() == prefix]
    org_ids = [oid for oid, o in context.organizations.items() if (o.code or "").lower() == prefix]
    owner: list[Any] = []
    if project_ids:
        owner.append(columns.project_id.in_(project_ids))
    if org_ids and columns.organization_id is not None:
        owner.append(and_(columns.project_id.is_(None), columns.organization_id.in_(org_ids)))
    if not owner:
        return None
    code_match = func.lower(cast(columns.code, String)) == rest if exact else _like(columns.code, rest)
    return and_(code_match, or_(*owner))


def _text_condition(artefact_type: str, provider: ArtefactSearchProvider, fields: list[str], terms: list[str], context: _Context) -> Any | None:
    """The match condition for one type, or `None` when it declares none of the selected fields."""
    columns = provider.columns
    carried = {f.key: f for f in provider.fields}
    per_term = []
    for term in terms:
        alternatives: list[Any] = []
        if "id" in fields:
            alternatives.append(_like(columns.code, term))
            qualified = _qualified_code_match(provider, term, context, exact=False)
            if qualified is not None:
                alternatives.append(qualified)
        if "title" in fields:
            alternatives.append(_like(columns.title, term))
        if "tags" in fields:
            alternatives.append(_tag_exists(artefact_type, columns.id, term))
        if COMMENTS_FIELD in fields and provider.comments is not None:
            alternatives.append(_comment_exists(provider.comments, columns.id, term))
        alternatives.extend(_like(carried[k].column, term) for k in fields if k in carried)
        if not alternatives:
            return None
        per_term.append(or_(*alternatives))
    return and_(*per_term)


def _tier(provider: ArtefactSearchProvider, full: str, context: _Context) -> Any:
    """Relevance tier: 0 exact code, 1 code prefix, 2 title contains, 3 anything else."""
    columns = provider.columns
    code = func.lower(cast(columns.code, String))
    exact: Any = code == full
    qualified = _qualified_code_match(provider, full, context, exact=True)
    if qualified is not None:
        exact = or_(exact, qualified)
    return case(
        (exact, 0),
        (code.like(f"{_escape_like(full)}%", escape="\\"), 1),
        (_like(columns.title, full), 2),
        else_=3,
    )


def _scope_condition(provider: ArtefactSearchProvider, project_ids: list[uuid.UUID], organization_ids: list[uuid.UUID]) -> Any:
    """Records of the allowed projects, plus (for an organisation-owned type) the organisations' own."""
    columns = provider.columns
    owned = columns.project_id.in_(project_ids)
    if (provider.organization_owned or provider.organization_subcomponent) and columns.organization_id is not None:
        return or_(owned, and_(columns.project_id.is_(None), columns.organization_id.in_(organization_ids)))
    return owned


def _filters(provider: ArtefactSearchProvider, params: SearchParams) -> list[Any]:
    columns = provider.columns
    conditions: list[Any] = list(provider.where)
    if not params.include_archived:
        conditions.append(columns.is_archived.is_(False))
    if params.statuses:
        conditions.append(cast(columns.status, String).in_(params.statuses))
    if params.updated_from is not None:
        conditions.append(columns.updated_at >= params.updated_from)
    if params.updated_to is not None:
        conditions.append(columns.updated_at <= params.updated_to)
    return conditions


def _type_conditions(
    artefact_type: str, provider: ArtefactSearchProvider, params: SearchParams, fields: list[str], terms: list[str], context: _Context,
) -> list[Any] | None:
    """Every `WHERE` condition for one type (scope, text, filters, scope restriction), or `None`
    when the type declares none of the selected fields."""
    match = _text_condition(artefact_type, provider, fields, terms, context)
    if match is None:
        return None
    project_ids = context.allowed.get(artefact_type, [])
    if provider.organization_subcomponent:
        organization_ids = sorted(context.org_allowed.get(artefact_type, []))
    else:
        organization_ids = sorted({context.projects[pid].organization_id for pid in project_ids})
    conditions = [_scope_condition(provider, project_ids, organization_ids), match, *_filters(provider, params)]
    if context.restrictions is not None:
        conditions.append(context.restrictions[artefact_type])
    return conditions


def _run(db: Session, statement: Any) -> list[Any]:
    """Executes a search statement, turning a statement timeout into `SearchTimeout`."""
    try:
        return list(db.execute(statement).all())
    except OperationalError as exc:
        if getattr(exc.orig, "pgcode", None) == "57014":
            db.rollback()
            raise SearchTimeout from exc
        raise


def _count(db: Session, provider: ArtefactSearchProvider, conditions: list[Any]) -> int:
    """Matches of one type, counted up to `MAX_DEPTH + 1`."""
    limited = select(provider.columns.id).select_from(provider.from_clause).where(*conditions).limit(MAX_DEPTH + 1).subquery()
    return int(_run(db, select(func.count()).select_from(limited))[0][0])


# --- rows ------------------------------------------------------------------------------------


@dataclass
class _Row:
    """A fetched record before shaping."""

    type: str
    id: uuid.UUID
    project_id: uuid.UUID | None
    code: str
    title: str
    status: str | None
    is_archived: bool
    updated_at: datetime | None
    organization_id: uuid.UUID | None
    owner_id: uuid.UUID | None
    tier: int
    field_values: dict[str, str]
    via_project_id: uuid.UUID | None = None


def _status_value(raw: Any) -> str | None:
    """A status column's string value (an enum member's `.value`)."""
    if raw is None:
        return None
    return str(getattr(raw, "value", raw))


def _fetch_type(
    db: Session, artefact_type: str, provider: ArtefactSearchProvider, conditions: list[Any], params: SearchParams, fields: list[str],
    full: str, context: _Context, row_limit: int,
) -> list[_Row]:
    """Fetches up to `row_limit` rows of one type in rank order."""
    columns = provider.columns
    selected_fields = [f for f in provider.fields if f.key in fields]
    tier = _tier(provider, full, context)
    wanted = [
        columns.id, columns.project_id, cast(columns.code, String), cast(columns.title, String), columns.status,
        columns.is_archived, columns.updated_at,
        columns.organization_id if columns.organization_id is not None else literal(None),
        columns.owner_id if columns.owner_id is not None else literal(None),
        tier,
        *[cast(f.column, String) for f in selected_fields],
    ]
    order = [columns.updated_at.desc(), columns.id]
    if params.sort == "relevance":
        order.insert(0, tier)
    statement = select(*wanted).select_from(provider.from_clause).where(*conditions).order_by(*order).limit(row_limit)
    rows: list[_Row] = []
    for r in _run(db, statement):
        rows.append(
            _Row(
                type=artefact_type, id=r[0], project_id=r[1], code=r[2] or "", title=r[3] or "", status=_status_value(r[4]),
                is_archived=bool(r[5]), updated_at=r[6], organization_id=r[7], owner_id=r[8], tier=int(r[9]),
                field_values={f.key: (r[10 + i] or "") for i, f in enumerate(selected_fields)},
            )
        )
    return rows


def _visible_organization_owned(db: Session, artefact_type: str, rows: list[_Row], context: _Context) -> list[_Row]:
    """Keeps the project-owned rows and the organisation-owned rows some allowed project may see.

    The owning module's visibility rule (`get_many_in_project`) decides, so a record hidden from a
    project is not found from it. An organisation-owned row records the project it was found through.
    """
    pending = {r.id: r for r in rows if r.project_id is None}
    if not pending:
        return rows
    seen: dict[uuid.UUID, uuid.UUID] = {}
    for project_id in context.allowed.get(artefact_type, [])[:_ORG_VISIBILITY_PROJECT_CAP]:
        remaining = [i for i in pending if i not in seen and pending[i].organization_id == context.projects[project_id].organization_id]
        if not remaining:
            continue
        found = get_artefact_summaries_in_project(db, project_id, artefact_type, remaining) or {}
        for record_id in found:
            seen[record_id] = project_id
    kept = []
    for r in rows:
        if r.project_id is not None:
            kept.append(r)
        elif r.id in seen:
            r.via_project_id = seen[r.id]
            kept.append(r)
    return kept


def _project_rows(
    db: Session, params: SearchParams, fields: list[str], terms: list[str], full: str, context: _Context, row_limit: int
) -> tuple[list[_Row], int]:
    """Projects as results (name and code, optionally the summary): rows and the capped count."""
    allowed = list(context.projects)
    if not allowed:
        return [], 0
    per_term = []
    for term in terms:
        alternatives = [_like(Project.code, term)] if "id" in fields else []
        if "title" in fields:
            alternatives.append(_like(Project.name, term))
        if "description" in fields:
            alternatives.append(_like(Project.summary, term))
        if not alternatives:
            return [], 0
        per_term.append(or_(*alternatives))
    conditions = [Project.id.in_(allowed), and_(*per_term)]
    if not params.include_archived:
        conditions.append(Project.is_archived.is_(False))
    if params.updated_from is not None:
        conditions.append(Project.updated_at >= params.updated_from)
    if params.updated_to is not None:
        conditions.append(Project.updated_at <= params.updated_to)
    code = func.lower(Project.code)
    tier = case((code == full, 0), (code.like(f"{_escape_like(full)}%", escape="\\"), 1), (_like(Project.name, full), 2), else_=3)
    order = [Project.updated_at.desc(), Project.id]
    if params.sort == "relevance":
        order.insert(0, tier)
    count = int(_run(db, select(func.count()).select_from(select(Project.id).where(*conditions).limit(MAX_DEPTH + 1).subquery()))[0][0])
    rows = [
        _Row(
            type=PROJECT_TYPE, id=r[0], project_id=r[0], code=r[1], title=r[2], status=None, is_archived=bool(r[3]), updated_at=r[4],
            organization_id=r[5], owner_id=None, tier=int(r[6]), field_values={"description": r[7] or ""},
        )
        for r in _run(
            db,
            select(Project.id, Project.code, Project.name, Project.is_archived, Project.updated_at, Project.organization_id, tier, Project.summary)
            .where(*conditions).order_by(*order).limit(row_limit),
        )
    ]
    return rows, count


# --- shaping ---------------------------------------------------------------------------------


def _window(text_: str, terms: list[str]) -> tuple[str, list[tuple[int, int]]] | None:
    """A window of `text_` around the first match of any term, with the match ranges inside it."""
    lowered = text_.lower()
    hits = [(lowered.find(t), t) for t in terms if t and lowered.find(t) >= 0]
    if not hits:
        return None
    first = min(i for i, _ in hits)
    start = max(0, first - _SNIPPET_BEFORE)
    end = min(len(text_), first + _SNIPPET_AFTER)
    window = text_[start:end]
    lowered_window = window.lower()
    ranges: list[tuple[int, int]] = []
    for term in terms:
        if not term:
            continue
        for m in re.finditer(re.escape(term), lowered_window):
            ranges.append((m.start(), m.end()))
    ranges = sorted(set(ranges))[:20]
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(text_) else ""
    shift = len(prefix)
    return f"{prefix}{window}{suffix}", [(s + shift, e + shift) for s, e in ranges]


def _tag_names(db: Session, rows: list[_Row]) -> dict[tuple[str, uuid.UUID], list[str]]:
    """The tag names of the given records, in one query."""
    if not rows:
        return {}
    by_type: dict[str, list[uuid.UUID]] = {}
    for r in rows:
        by_type.setdefault(r.type, []).append(r.id)
    found: dict[tuple[str, uuid.UUID], list[str]] = {}
    clauses = [and_(ArtefactTag.artefact_type == t, ArtefactTag.artefact_id.in_(ids)) for t, ids in by_type.items() if t != PROJECT_TYPE]
    if not clauses:
        return {}
    for artefact_type, artefact_id, name in db.execute(
        select(ArtefactTag.artefact_type, ArtefactTag.artefact_id, Tag.name)
        .join(Tag, Tag.id == ArtefactTag.tag_id)
        .where(or_(*clauses))
        .order_by(Tag.name_key)
    ).all():
        found.setdefault((artefact_type, artefact_id), []).append(name)
    return found


def _comment_texts(db: Session, rows: list[_Row], terms: list[str], providers: dict[str, ArtefactSearchProvider]) -> dict[tuple[str, uuid.UUID], str]:
    """The earliest comment containing a term, for each of the given records, one query per type."""
    by_type: dict[str, list[uuid.UUID]] = {}
    for r in rows:
        if r.type != PROJECT_TYPE and providers[r.type].comments is not None:
            by_type.setdefault(r.type, []).append(r.id)
    found: dict[tuple[str, uuid.UUID], str] = {}
    for artefact_type, ids in by_type.items():
        comments = providers[artefact_type].comments
        statement = (
            select(comments.record_id, comments.body)
            .where(comments.record_id.in_(ids), *comments.where, or_(*[_like(comments.body, t) for t in terms]))
            .order_by(comments.created_at)
        )
        for record_id, body in _run(db, statement):
            found.setdefault((artefact_type, record_id), body or "")
    return found


def _snippet(
    row: _Row, fields: list[str], terms: list[str], tags: dict[tuple[str, uuid.UUID], list[str]], labels: dict[str, str],
    comment_texts: dict[tuple[str, uuid.UUID], str] | None = None,
) -> Snippet | None:
    """The first of Tags and the declared fields (in selection order) that contains a term."""
    if "tags" in fields:
        matching = [n for n in tags.get((row.type, row.id), []) if any(t in n.lower() for t in terms)]
        if matching:
            joined = ", ".join(matching)
            windowed = _window(joined, terms)
            if windowed:
                return Snippet("tags", labels.get("tags", "Tags"), windowed[0], windowed[1])
    for key in fields:
        value = row.field_values.get(key)
        if not value:
            continue
        windowed = _window(" ".join(value.split()), terms)
        if windowed:
            return Snippet(key, labels.get(key, key), windowed[0], windowed[1])
    comment = (comment_texts or {}).get((row.type, row.id))
    if comment:
        windowed = _window(" ".join(comment.split()), terms)
        if windowed:
            return Snippet(COMMENTS_FIELD, labels.get(COMMENTS_FIELD, _COMMENTS_LABEL), windowed[0], windowed[1])
    return None


def _shape(row: _Row, providers: dict[str, ArtefactSearchProvider], context: _Context, snippet: Snippet | None) -> SearchHit:
    """A `SearchHit` from a fetched row."""
    if row.type == PROJECT_TYPE:
        project = context.projects.get(row.id)
        organization = context.organizations.get(project.organization_id) if project else None
        return SearchHit(
            type=PROJECT_TYPE, type_label="Project", id=row.id, code=row.code, title=row.title, status=None, status_label=None,
            is_archived=row.is_archived, updated_at=row.updated_at, project_id=row.id, project_name=row.title, project_code=row.code,
            organization_id=row.organization_id, organization_code=organization.code if organization else None,
            open_type=PROJECT_TYPE, open_id=row.id, open_project_id=row.id, snippet=snippet, tier=row.tier,
        )
    provider = providers[row.type]
    owning = context.projects.get(row.project_id) if row.project_id is not None else None
    via = context.projects.get(row.via_project_id) if row.via_project_id is not None else None
    org_id = owning.organization_id if owning else row.organization_id
    organization = context.organizations.get(org_id) if org_id else None
    label = provider.status_labels.get(row.status or "", (row.status or "").replace("_", " ").capitalize()) if row.status else None
    open_type, open_id = (provider.open_owner_type, row.owner_id) if provider.open_owner_type and row.owner_id else (row.type, row.id)
    return SearchHit(
        type=row.type, type_label=get_artefact_type_label(row.type), id=row.id, code=row.code, title=row.title, status=row.status,
        status_label=label, is_archived=row.is_archived, updated_at=row.updated_at,
        project_id=row.project_id, project_name=owning.name if owning else None, project_code=owning.code if owning else None,
        organization_id=org_id, organization_code=organization.code if organization else None,
        open_type=open_type, open_id=open_id, open_project_id=(owning or via).id if (owning or via) else None, snippet=snippet,
        tier=row.tier,
    )


# --- entry point -----------------------------------------------------------------------------


def _validate(params: SearchParams) -> None:
    """Rejects a malformed request.

    Raises:
        HTTPException: 422 for a query that is too short or long, or a page past the depth limit.
    """
    query = " ".join(params.q.split())
    if len(query) < MIN_QUERY:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Search for at least {MIN_QUERY} characters.")
    if len(query) > MAX_QUERY:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Search text is limited to {MAX_QUERY} characters.")
    if params.offset + params.limit > MAX_DEPTH:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, f"Results are limited to the first {MAX_DEPTH}. Refine the search to narrow them."
        )


def run_search(db: Session, user: User, params: SearchParams) -> SearchResult:
    """Runs a search for `user`.

    Args:
        db: Active session (read only).
        user: The caller.
        params: The request.

    Returns:
        The page of hits and the data the filters need.

    Raises:
        HTTPException: 404 the scope or project is not found or not allowed; 422 a malformed request.
        SearchTimeout: The search ran past the statement timeout.
    """
    _validate(params)
    started = time.monotonic()
    db.execute(text(f"SET LOCAL statement_timeout = {STATEMENT_TIMEOUT_MS}"))
    with memoize_user_lookups(), memoize_module_state():
        context = _authorised_projects(db, user, params)
    providers = get_search_providers()
    offered_types = [t for t in context.searchable_types if t in providers]
    merged = _field_labels(sorted(offered_types))
    fields = resolve_fields(user, params.fields, set(merged))
    terms = _terms(params)
    full = " ".join(terms)
    wanted_types = set(params.types) if params.types is not None else None

    rows: list[_Row] = []
    counts: list[TypeCount] = []
    not_searched: list[tuple[str, str]] = []
    row_limit = params.offset + params.limit
    for artefact_type in sorted(offered_types, key=lambda t: get_artefact_type_label(t).lower()):
        provider = providers[artefact_type]
        conditions = _type_conditions(artefact_type, provider, params, fields, terms, context)
        if conditions is None:
            not_searched.append((artefact_type, get_artefact_type_label(artefact_type)))
            continue
        fetched: list[_Row] = []
        organisation_owned = provider.organization_owned
        selected = wanted_types is None or artefact_type in wanted_types
        count = None
        if organisation_owned:
            if selected or params.counts:
                fetched = _visible_organization_owned(
                    db, artefact_type, _fetch_type(db, artefact_type, provider, conditions, params, fields, full, context, _ORG_OWNED_FETCH), context
                )
                count = min(len(fetched), MAX_DEPTH + 1)
        else:
            if params.counts:
                count = _count(db, provider, conditions)
            if selected:
                fetched = _fetch_type(db, artefact_type, provider, conditions, params, fields, full, context, row_limit)
        if count:
            counts.append(TypeCount(artefact_type, get_artefact_type_label(artefact_type), min(count, MAX_DEPTH), count > MAX_DEPTH))
        if selected:
            rows.extend(fetched)

    if params.scope == "all" and (wanted_types is None or PROJECT_TYPE in wanted_types) and not params.statuses:
        project_rows, project_count = _project_rows(db, params, fields, terms, full, context, row_limit)
        if params.counts and project_count:
            counts.append(TypeCount(PROJECT_TYPE, "Project", min(project_count, MAX_DEPTH), project_count > MAX_DEPTH))
        rows.extend(project_rows)

    def rank(r: _Row) -> tuple:
        stamp = -(r.updated_at.timestamp() if r.updated_at else 0.0)
        return (r.tier, stamp, r.type, str(r.id)) if params.sort == "relevance" else (stamp, r.type, str(r.id))

    rows.sort(key=rank)
    page = rows[params.offset:params.offset + params.limit]
    tag_names = _tag_names(db, page) if "tags" in fields else {}
    field_labels = {k: v[0] for k, v in merged.items()}
    comment_texts = _comment_texts(db, page, terms, providers) if COMMENTS_FIELD in fields else {}
    hits = [_shape(r, providers, context, _snippet(r, fields, terms, tag_names, field_labels, comment_texts)) for r in page]
    total = None
    total_capped = False
    if params.counts:
        in_scope = sum(c.count for c in counts if wanted_types is None or c.type in wanted_types)
        total = min(in_scope, MAX_DEPTH)
        total_capped = any(c.capped for c in counts if wanted_types is None or c.type in wanted_types) or in_scope > MAX_DEPTH
    statuses: dict[str, str] = {}
    for artefact_type in offered_types:
        for value, label in providers[artefact_type].status_labels.items():
            statuses.setdefault(value, label)
    result = SearchResult(
        hits=hits, total=total, total_capped=total_capped, type_counts=sorted(counts, key=lambda c: c.label.lower()),
        fields_used=fields, not_searched=not_searched, statuses=sorted(statuses.items(), key=lambda s: s[1].lower()),
        organizations=_user_organizations(db, user.id), projects_truncated=context.truncated,
    )
    logger.info(
        "search scope=%s fields=%s match=%s sort=%s types=%d results=%d projects=%d ms=%d",
        params.scope.split(":")[0] if params.scope not in ("project", "all") else params.scope, ",".join(fields), params.match, params.sort,
        len(offered_types), len(hits), len(context.projects), int((time.monotonic() - started) * 1000),
    )
    return result


__all__ = [
    "COMMENTS_FIELD", "DEFAULT_FIELDS", "MAX_DEPTH", "MAX_QUERY", "MIN_QUERY", "PROJECT_TYPE", "SearchHit", "SearchParams",
    "SearchResult", "SearchTimeout",
    "SEARCH_DEFAULT_FIELDS_KEY", "SEARCH_INCLUDE_ORG_RECORDS_KEY", "Snippet", "TypeCount", "available_fields", "resolve_fields",
    "run_search", "validate_default_fields",
]
