"""
Module: services.changes

Builds the unified "project changes over time" timeline (C-A-10) by merging
four sources: generic audit events (group/role/project-structure changes),
requirement version history, change-request version history and, on request,
discussion comments (C-R-01, excluded by default per the requirement's
clarification — the caller opts in via `include_comments` or the Comments kind).

Responsibilities:
- `ChangeFilter`: every narrowing the History page offers (time range, type, event kinds, actors).
- `get_project_changes_page`: one page of the merged timeline and the total, **bounded work per page**:
  each filter is part of the source query, each source reads only its newest `offset + limit` rows and is
  counted separately, so the cost follows the page asked for and not the size of the project.
- `get_project_changes`: the whole filtered timeline, for the record activity panels that need all of it.
- Labels: the entry's event `kind`, the actor's name and, for a record of any registered type the viewer may
  see, its code and title (`record_label`), resolved for the returned page only.

Design decisions:
- Entries sort by `(timestamp, source, id)` descending so equal timestamps (several events in one request)
  page deterministically; a "Load more" never repeats or skips a row.
- A record a viewer may not see keeps its type and gets no label: the timeline reveals what happened, not the
  title of a record the viewer could not open (`services.link_graph.ArtefactResolver` is the visibility rule).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import ColumnElement, and_, false, func, not_, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.sql import Select

from app.models.audit import AuditEvent
from app.models.change_request import ChangeRequest, ChangeRequestVersion, ReviewComment
from app.models.enums import PrincipalType, ReviewTargetType
from app.models.organization import OrgGroup
from app.models.project import Project, ProjectGroup
from app.models.requirement import Requirement, RequirementVersion
from app.models.user import User
from app.modules.registry import get_all_registered_artefact_types
from app.schemas.changes import ChangeEntryOut
from app.schemas.principal import PrincipalOut, PrincipalRef
from app.services.activity_kinds import (
    AUDIT_TRAIL_ONLY_ACTIONS,
    AUDIT_TRAIL_ONLY_ENTITY_TYPES,
    COMMENTS,
    KIND_LABELS,
    action_kinds,
    actions_for_kinds,
    kind_of,
)
from app.services.activity_link_ends import attach_link_ends
from app.services.link_graph import ArtefactResolver
from app.services.principals import UNKNOWN_USER_LABEL, principal_labels, principal_member_ids
from app.services.rbac import get_effective_org_roles

#: Entity types whose title is read from their own version history (`_title_versioned_entries`).
_VERSIONED = ("requirement", "change_request")

# Every one of these (entity_type, action) pairs is logged by a router handler that *also* calls
# `apply_new_version`/`create_requirement` (for "requirement") or inserts the version-1
# `ChangeRequestVersion` row (for "change_request") in the same request. The version-history queries
# already synthesize an equivalent, more informative entry for each (carrying `change_note`, e.g.
# "Approved directly."), so the generic `AuditEvent` row would otherwise show up a second time for the
# same transition. `archived`/`unarchived`/`review_recorded` (requirement) and `submitted`/`withdrawn`/
# approve-reject (change_request) don't bump a version and are unaffected. `completed`/`uncompleted` do
# not bump a version either, so their `AuditEvent` is the only record of the action.
VERSION_HISTORY_COVERED_ACTIONS: dict[str, set[str]] = {
    "requirement": {"created", "updated", "approved"},
    "change_request": {"created"},
}


@dataclass(frozen=True)
class ChangeFilter:
    """The narrowing of one timeline request.

    Attributes:
        since / until: Optional inclusive time range, as UTC instants.
        include_comments: Whether discussion-thread comments are merged in (also implied by the `comments` kind).
        entity_type: Only events about this entity type.
        entity_id: Only events about one record (a record's own panel).
        kinds: Only events of these kinds (`services.activity_kinds`); empty means every kind.
        actor_ids: Only events by these users; `None` means any actor. An empty set matches nothing (a group
            with no members), which is a real answer and not "no filter".
        oldest_first: Order the page oldest first (the Time column's sort); the default is newest first.
    """

    since: datetime | None = None
    until: datetime | None = None
    include_comments: bool = False
    entity_type: str | None = None
    entity_id: UUID | None = None
    kinds: frozenset[str] = field(default_factory=frozenset)
    actor_ids: frozenset[UUID] | None = None
    oldest_first: bool = False


@dataclass
class _Source:
    """One merge source: a query already narrowed by the filter, how to turn a row into an entry, a rank."""

    rank: int
    query: Select[Any]
    sort_time: Any
    sort_id: Any
    build: Any


def _action_clause(column: Any, kinds: frozenset[str]) -> ColumnElement[bool] | None:
    """`column` restricted to the actions of `kinds`; `None` when no kind filter applies."""
    if not kinds:
        return None
    actions, include_other = actions_for_kinds(kinds)
    clause: ColumnElement[bool] = column.in_(actions) if actions else false()
    if include_other:
        clause = or_(clause, not_(column.in_(action_kinds().keys())))
    return clause


def _audit_source(project_id: UUID, flt: ChangeFilter) -> _Source:
    """Audit events of the project, with every filter in the query."""
    query = select(AuditEvent).where(AuditEvent.project_id == project_id)
    if flt.entity_id is not None:
        query = query.where(AuditEvent.entity_id == str(flt.entity_id))
    if flt.entity_type is not None:
        query = query.where(AuditEvent.entity_type == flt.entity_type)
    if flt.since is not None:
        query = query.where(AuditEvent.created_at >= flt.since)
    if flt.until is not None:
        query = query.where(AuditEvent.created_at <= flt.until)
    if flt.actor_ids is not None:
        query = query.where(AuditEvent.actor_id.in_(flt.actor_ids))
    clause = _action_clause(AuditEvent.action, flt.kinds)
    if clause is not None:
        query = query.where(clause)
    covered = [
        and_(AuditEvent.entity_type == entity_type, AuditEvent.action.in_(actions))
        for entity_type, actions in VERSION_HISTORY_COVERED_ACTIONS.items()
    ]
    covered.append(
        and_(AuditEvent.entity_type.in_(AUDIT_TRAIL_ONLY_ENTITY_TYPES), AuditEvent.action.in_(AUDIT_TRAIL_ONLY_ACTIONS))
    )
    query = query.where(not_(or_(*covered)))

    def build(event: AuditEvent) -> ChangeEntryOut:
        return ChangeEntryOut(
            timestamp=event.created_at, entity_type=event.entity_type, entity_id=event.entity_id,
            action=event.action, actor_id=event.actor_id, detail=event.detail,
        )

    return _Source(0, query, AuditEvent.created_at, AuditEvent.id, build)


def _version_actions(flt: ChangeFilter) -> tuple[bool, bool]:
    """Whether version 1 (`created`) and later versions (`updated`) pass the kind filter."""
    if not flt.kinds:
        return True, True
    known = action_kinds()
    return kind_of("created", known) in flt.kinds, kind_of("updated", known) in flt.kinds


def _version_clause(version_number: Any, flt: ChangeFilter) -> ColumnElement[bool]:
    """The version-number condition that keeps the entries whose derived action the kind filter wants."""
    first, later = _version_actions(flt)
    if first and later:
        return version_number >= 1
    if first:
        return version_number == 1
    if later:
        return version_number > 1
    return false()


def _requirement_source(project_id: UUID, flt: ChangeFilter) -> _Source | None:
    """Requirement version history as `created` (version 1) and `updated` entries."""
    if flt.entity_type not in (None, "requirement"):
        return None
    query = (
        select(RequirementVersion, Requirement.unique_code)
        .join(Requirement, Requirement.id == RequirementVersion.requirement_id)
        .where(Requirement.project_id == project_id, _version_clause(RequirementVersion.version_number, flt))
    )
    if flt.entity_id is not None:
        query = query.where(RequirementVersion.requirement_id == flt.entity_id)
    if flt.since is not None:
        query = query.where(RequirementVersion.created_at >= flt.since)
    if flt.until is not None:
        query = query.where(RequirementVersion.created_at <= flt.until)
    if flt.actor_ids is not None:
        query = query.where(RequirementVersion.created_by.in_(flt.actor_ids))

    def build(row: Any) -> ChangeEntryOut:
        version, unique_code = row
        return ChangeEntryOut(
            timestamp=version.created_at, entity_type="requirement", entity_id=str(version.requirement_id),
            action="created" if version.version_number == 1 else "updated", actor_id=version.created_by,
            detail={"unique_code": unique_code, "status": version.status.value, "change_note": version.change_note},
        )

    return _Source(1, query, RequirementVersion.created_at, RequirementVersion.id, build)


def _change_request_source(project_id: UUID, flt: ChangeFilter) -> _Source | None:
    """Change request version history as `created` (version 1) and `updated` entries."""
    if flt.entity_type not in (None, "change_request"):
        return None
    query = (
        select(ChangeRequestVersion, ChangeRequest.status, ChangeRequest.unique_code)
        .join(ChangeRequest, ChangeRequest.id == ChangeRequestVersion.change_request_id)
        .where(ChangeRequest.project_id == project_id, _version_clause(ChangeRequestVersion.version_number, flt))
    )
    if flt.entity_id is not None:
        query = query.where(ChangeRequestVersion.change_request_id == flt.entity_id)
    if flt.since is not None:
        query = query.where(ChangeRequestVersion.created_at >= flt.since)
    if flt.until is not None:
        query = query.where(ChangeRequestVersion.created_at <= flt.until)
    if flt.actor_ids is not None:
        query = query.where(ChangeRequestVersion.created_by.in_(flt.actor_ids))

    def build(row: Any) -> ChangeEntryOut:
        version, cr_status, unique_code = row
        return ChangeEntryOut(
            timestamp=version.created_at, entity_type="change_request", entity_id=str(version.change_request_id),
            action="created" if version.version_number == 1 else "updated", actor_id=version.created_by,
            detail={"unique_code": unique_code, "proposed_name": version.proposed_name, "status": cr_status.value},
        )

    return _Source(2, query, ChangeRequestVersion.created_at, ChangeRequestVersion.id, build)


def _comment_source(project_id: UUID, flt: ChangeFilter) -> _Source | None:
    """Discussion comments on the project's requirements and change requests."""
    wants_comments = flt.include_comments or COMMENTS in flt.kinds
    if not wants_comments or (flt.kinds and COMMENTS not in flt.kinds):
        return None
    if flt.entity_type not in (None, ReviewTargetType.REQUIREMENT.value, ReviewTargetType.CHANGE_REQUEST.value):
        return None
    in_project = or_(
        and_(
            ReviewComment.target_type == ReviewTargetType.REQUIREMENT,
            ReviewComment.target_id.in_(select(Requirement.id).where(Requirement.project_id == project_id)),
        ),
        and_(
            ReviewComment.target_type == ReviewTargetType.CHANGE_REQUEST,
            ReviewComment.target_id.in_(select(ChangeRequest.id).where(ChangeRequest.project_id == project_id)),
        ),
    )
    query = select(ReviewComment).where(in_project)
    if flt.entity_type is not None:
        query = query.where(ReviewComment.target_type == ReviewTargetType(flt.entity_type))
    if flt.entity_id is not None:
        query = query.where(ReviewComment.target_id == flt.entity_id)
    if flt.since is not None:
        query = query.where(ReviewComment.created_at >= flt.since)
    if flt.until is not None:
        query = query.where(ReviewComment.created_at <= flt.until)
    if flt.actor_ids is not None:
        query = query.where(ReviewComment.author_id.in_(flt.actor_ids))

    def build(comment: ReviewComment) -> ChangeEntryOut:
        return ChangeEntryOut(
            timestamp=comment.created_at, entity_type=comment.target_type.value, entity_id=str(comment.target_id),
            action="comment_added", actor_id=comment.author_id, detail={"body": comment.body},
        )

    return _Source(3, query, ReviewComment.created_at, ReviewComment.id, build)


def _sources(project_id: UUID, flt: ChangeFilter) -> list[_Source]:
    """The merge sources that can contribute to `flt` (a source its filter excludes is not queried at all)."""
    found = [
        _audit_source(project_id, flt),
        _requirement_source(project_id, flt),
        _change_request_source(project_id, flt),
        _comment_source(project_id, flt),
    ]
    return [source for source in found if source is not None]


def build_filter(
    db: Session, project: Project, *, since: datetime | None, until: datetime | None, include_comments: bool,
    entity_type: str | None, kinds: Sequence[str], actors: Sequence[str], oldest_first: bool = False,
) -> ChangeFilter:
    """Validates the History page's query parameters and turns them into a `ChangeFilter`.

    Args:
        db: An active database session (read only).
        project: The project reported on.
        since / until: Optional time range (UTC instants).
        include_comments: Whether discussion comments are merged in.
        entity_type: Optional entity type.
        kinds: Kind keys (`services.activity_kinds.KIND_LABELS`).
        oldest_first: Whether the page is ordered oldest first.
        actors: Principals as `user:<id>`, `org_group:<id>` or `project_group:<id>`; a group stands for its
            effective members (`services.principals.principal_member_ids`).

    Returns:
        The filter; `actor_ids` is `None` when no actor was named.

    Raises:
        HTTPException: 422 for an unknown kind, a malformed principal, or a group of another organisation or
            project. A user is not checked against the organisation: a person who has since left still has
            events, and the filter only narrows what the caller may already see.
    """
    unknown = [kind for kind in kinds if kind not in KIND_LABELS]
    if unknown:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Unknown event kind: {unknown[0]}.")
    actor_ids: set[UUID] | None = None
    for text in actors:
        kind_text, _, id_text = text.partition(":")
        try:
            ref = PrincipalRef(type=PrincipalType(kind_text), id=UUID(id_text))
        except ValueError:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, "A person or group is written type:id (user, org_group or project_group).",
            ) from None
        if ref.type is PrincipalType.ORG_GROUP:
            group = db.get(OrgGroup, ref.id)
            allowed = group is not None and group.organization_id == project.organization_id
        elif ref.type is PrincipalType.PROJECT_GROUP:
            project_group = db.get(ProjectGroup, ref.id)
            allowed = project_group is not None and project_group.project_id == project.id
        else:
            allowed = True
        if not allowed:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "That group does not belong to this project.")
        actor_ids = (actor_ids or set()) | principal_member_ids(db, ref)
    return ChangeFilter(
        since=since, until=until, include_comments=include_comments, entity_type=entity_type,
        kinds=frozenset(kinds), actor_ids=None if actor_ids is None else frozenset(actor_ids), oldest_first=oldest_first,
    )


def named_actors(db: Session, project: Project, actors: Sequence[str]) -> list[PrincipalOut]:
    """The people and groups named in a History filter, resolved for display (the filter chips).

    Args:
        db: An active database session (read only).
        project: The project reported on.
        actors: Principals as `user:<id>`, `org_group:<id>` or `project_group:<id>`.

    Returns:
        One entry per principal, in request order. A group that is not this organisation's or this project's
        is refused like the filter refuses it; a user who is neither a member of the organisation nor an actor in
        this project's history gets the placeholder label, so the endpoint never names an arbitrary account.

    Raises:
        HTTPException: 422 for a malformed principal or a group of another organisation or project.
    """
    build_filter(
        db, project, since=None, until=None, include_comments=False, entity_type=None, kinds=[], actors=actors,
    )
    refs = [PrincipalRef(type=PrincipalType(text.partition(":")[0]), id=UUID(text.partition(":")[2])) for text in actors]
    labels = principal_labels(db, refs)
    shown: list[PrincipalOut] = []
    for ref in refs:
        out = labels[(ref.type.value, ref.id)]
        if ref.type is PrincipalType.USER and out.exists and not _is_known_in(db, project, ref.id):
            out = PrincipalOut(type=PrincipalType.USER, id=ref.id, label=UNKNOWN_USER_LABEL, exists=False)
        shown.append(out)
    return shown


def _is_known_in(db: Session, project: Project, user_id: UUID) -> bool:
    """Whether `user_id` belongs to the project's organisation or has acted in the project."""
    if get_effective_org_roles(db, user_id, project.organization_id):
        return True
    return db.scalar(
        select(AuditEvent.id).where(AuditEvent.project_id == project.id, AuditEvent.actor_id == user_id).limit(1)
    ) is not None


def history_entity_types(db: Session, project_id: UUID) -> list[str]:
    """The entity types this project has events for, sorted: what the History page's Type filter offers.

    Args:
        db: An active database session (read only).
        project_id: The project.

    Returns:
        Distinct audit entity types plus `requirement` and `change_request` when they have versions.
    """
    types = set(db.scalars(select(AuditEvent.entity_type).where(AuditEvent.project_id == project_id).distinct()).all())
    if db.scalar(select(Requirement.id).where(Requirement.project_id == project_id).limit(1)) is not None:
        types.add("requirement")
    if db.scalar(select(ChangeRequest.id).where(ChangeRequest.project_id == project_id).limit(1)) is not None:
        types.add("change_request")
    return sorted(types)


def get_project_changes_page(
    db: Session, project: Project, flt: ChangeFilter, *, limit: int, offset: int = 0, viewer_id: UUID | None = None,
) -> tuple[list[ChangeEntryOut], int]:
    """One page of the filtered timeline, newest first, and how many entries match.

    Args:
        db: An active database session (read only).
        project: The project reported on (the route has authorised the viewer for it).
        flt: The narrowing.
        limit: Entries to return.
        offset: Entries to skip.
        viewer_id: The viewing user; given, each entry about a record of a registered type the viewer may see
            gains its `record_label`.

    Returns:
        `(entries, total)`; `total` counts every matching entry, not only this page.
    """
    window = offset + limit
    ordered: list[tuple[Any, int, str, ChangeEntryOut]] = []
    total = 0
    for source in _sources(project.id, flt):
        total += db.scalar(select(func.count()).select_from(source.query.order_by(None).subquery())) or 0
        ordering = (source.sort_time.asc(), source.sort_id.asc()) if flt.oldest_first else (source.sort_time.desc(), source.sort_id.desc())
        page = db.execute(source.query.order_by(*ordering).limit(window)).all()
        for row in page:
            entry = source.build(row[0] if len(row) == 1 else row)
            ordered.append((entry.timestamp, source.rank, str(row[0].id if len(row) == 1 else row[0].id), entry))
    ordered.sort(key=lambda item: item[:3], reverse=not flt.oldest_first)
    entries = [item[3] for item in ordered[offset:window]]
    _annotate(db, project, entries, viewer_id)
    return entries, total


def get_project_changes(
    db: Session, project_id: UUID, *,
    since: datetime | None, until: datetime | None, include_comments: bool = False, entity_type: str | None = None,
    entity_id: UUID | None = None,
) -> list[ChangeEntryOut]:
    """The whole filtered timeline of a project, newest first (the record activity panels use all of it).

    Args:
        db: An active database session.
        project_id: The project to report on.
        since / until: Optional inclusive time range filter.
        include_comments: Whether to include discussion-thread comments (excluded by default, per C-A-10's
            clarification).
        entity_type: Optional filter to a single entity type (e.g. "requirement", "change_request").
        entity_id: Optional filter to one record (used with `entity_type` "requirement" or "change_request");
            pushed into the queries so a single record's activity does not load the whole project's.

    Returns:
        Entries sorted newest-first.
    """
    flt = ChangeFilter(
        since=since, until=until, include_comments=include_comments, entity_type=entity_type, entity_id=entity_id,
    )
    ordered: list[tuple[Any, int, str, ChangeEntryOut]] = []
    for source in _sources(project_id, flt):
        for row in db.execute(source.query).all():
            entry = source.build(row[0] if len(row) == 1 else row)
            ordered.append((entry.timestamp, source.rank, str(row[0].id), entry))
    ordered.sort(key=lambda item: item[:3], reverse=True)
    entries = [item[3] for item in ordered]
    _annotate(db, None, entries, None)
    return entries


def _annotate(db: Session, project: Project | None, entries: list[ChangeEntryOut], viewer_id: UUID | None) -> None:
    """Fills the titles, actor names, kinds and (for a viewer) record labels of `entries` in place."""
    _title_versioned_entries(db, entries)
    attach_actor_names(db, entries)
    known = action_kinds()
    for entry in entries:
        entry.kind = kind_of(entry.action, known)
    if project is not None and viewer_id is not None:
        _attach_record_labels(db, project, viewer_id, entries)
        attach_link_ends(db, project, viewer_id, entries)


def _attach_record_labels(db: Session, project: Project, viewer_id: UUID, entries: list[ChangeEntryOut]) -> None:
    """Sets `record_label` on entries about a record of a registered type the viewer may see.

    Requirements and change requests already carry their code and title in `detail` (`_title_versioned_entries`);
    every other registered type is labelled through the same resolver the Links panel uses, one lookup per type.
    """
    registered = get_all_registered_artefact_types()
    wanted: dict[str, set[UUID]] = {}
    for entry in entries:
        if entry.entity_type in _VERSIONED or entry.entity_type not in registered:
            continue
        try:
            wanted.setdefault(entry.entity_type, set()).add(UUID(entry.entity_id))
        except ValueError:
            continue
    if not wanted:
        return
    resolver = ArtefactResolver(db, project, viewer_id)
    resolver.resolve(wanted)
    for entry in entries:
        if entry.entity_type not in wanted:
            continue
        try:
            summary = resolver.visible((entry.entity_type, UUID(entry.entity_id)))
        except ValueError:
            continue
        if summary is not None:
            entry.record_label = summary.label


def _title_versioned_entries(db: Session, entries: list[ChangeEntryOut]) -> None:
    """Guarantees every requirement/change-request entry carries a resolvable code and current title.

    Not only the entries sourced from version history (which already had `unique_code`/`proposed_name`), but
    also the generic `AuditEvent`-sourced ones (archive, review, file-attach, ...), whose `detail` held only
    whatever that call site logged. Resolved from *current* state, not the state at the time of the event, so a
    since-renamed item shows its current title consistently on every row.
    """
    requirement_entries = [e for e in entries if e.entity_type == "requirement"]
    if requirement_entries:
        req_ids = {UUID(e.entity_id) for e in requirement_entries}
        unique_codes = dict(
            db.execute(select(Requirement.id, Requirement.unique_code).where(Requirement.id.in_(req_ids))).tuples().all()
        )
        current_names: dict[UUID, tuple[str, int]] = {}
        for req_id, name, version_number in db.execute(
            select(RequirementVersion.requirement_id, RequirementVersion.name, RequirementVersion.version_number)
            .where(RequirementVersion.requirement_id.in_(req_ids))
        ).all():
            if req_id not in current_names or version_number > current_names[req_id][1]:
                current_names[req_id] = (name, version_number)
        for e in requirement_entries:
            rid = UUID(e.entity_id)
            detail = dict(e.detail or {})
            if rid in unique_codes:
                detail["unique_code"] = unique_codes[rid]
            if rid in current_names:
                detail["name"] = current_names[rid][0]
            e.detail = detail

    cr_entries = [e for e in entries if e.entity_type == "change_request"]
    if cr_entries:
        cr_ids = {UUID(e.entity_id) for e in cr_entries}
        current_titles: dict[UUID, tuple[str | None, int]] = {}
        for cr_id, proposed_name, version_number in db.execute(
            select(ChangeRequestVersion.change_request_id, ChangeRequestVersion.proposed_name, ChangeRequestVersion.version_number)
            .where(ChangeRequestVersion.change_request_id.in_(cr_ids))
        ).all():
            if cr_id not in current_titles or version_number > current_titles[cr_id][1]:
                current_titles[cr_id] = (proposed_name, version_number)
        # A MODIFY_REQUIREMENT change request that doesn't propose changing
        # the name (changed_fields tracking, see docs/decisions.md's
        # "Change request field-level tracking" entry) has no proposed_name
        # of its own — fall back to the target requirement's own current
        # name so the activity feed still shows a real title instead of a
        # blank one, matching this block's own "always a resolvable
        # current title" intent. NEW_REQUIREMENT change requests always
        # have a real proposed_name (validated at creation), so this
        # fallback never triggers for those.
        missing_name_cr_ids = {cid for cid, (name, _) in current_titles.items() if name is None}
        fallback_names: dict[UUID, str] = {}
        if missing_name_cr_ids:
            cr_to_requirement = dict(
                db.execute(
                    select(ChangeRequest.id, ChangeRequest.requirement_id).where(ChangeRequest.id.in_(missing_name_cr_ids))
                ).tuples().all()
            )
            fallback_requirement_ids = {rid for rid in cr_to_requirement.values() if rid is not None}
            requirement_current_names: dict[UUID, tuple[str, int]] = {}
            if fallback_requirement_ids:
                for req_id, name, version_number in db.execute(
                    select(RequirementVersion.requirement_id, RequirementVersion.name, RequirementVersion.version_number)
                    .where(RequirementVersion.requirement_id.in_(fallback_requirement_ids))
                ).all():
                    if req_id not in requirement_current_names or version_number > requirement_current_names[req_id][1]:
                        requirement_current_names[req_id] = (name, version_number)
            for cr_id, requirement_id in cr_to_requirement.items():
                if requirement_id is not None and requirement_id in requirement_current_names:
                    fallback_names[cr_id] = requirement_current_names[requirement_id][0]
        for e in cr_entries:
            cid = UUID(e.entity_id)
            if cid in current_titles:
                detail = dict(e.detail or {})
                detail["proposed_name"] = current_titles[cid][0] or fallback_names.get(cid)
                e.detail = detail


def attach_actor_names(db: Session, entries: list[ChangeEntryOut]) -> None:
    """Fills `actor_display_name` on every entry that has an actor ("Unknown user" for a deleted one).

    Args:
        db: An active database session.
        entries: The entries to annotate in place.
    """
    actor_ids = {e.actor_id for e in entries if e.actor_id is not None}
    display_names = {
        u.id: u.display_name for u in db.scalars(select(User).where(User.id.in_(actor_ids))).all()
    } if actor_ids else {}
    for e in entries:
        if e.actor_id is not None:
            e.actor_display_name = display_names.get(e.actor_id, "Unknown user")
