"""
Module: services.requirements

Core requirement business logic: unique ID generation (C-G-06, C-G-07),
versioned content changes (C-A-02), the change-request-only edit lock once a
requirement is approved (C-G-12), archival (C-A-06), and keyword/traceability
management (C-M-01, C-G-09).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.models.change_request import ChangeRequest
from app.models.custom_field import CustomFieldEntityKind
from app.models.engagement import Subscription
from app.models.enums import (
    ChangeRequestStatus,
    PrincipalType,
    RequirementLevel,
    RequirementStatus,
    ReviewTargetType,
)
from app.models.organization import Organization
from app.models.project import Project, ProjectCategory, ProjectComponent
from app.models.requirement import Requirement, RequirementVersion
from app.models.user import User
from app.modules.registry import ArtefactChange
from app.schemas.principal import PrincipalOut, PrincipalRef
from app.services import engagement
from app.services import tags as tag_service
from app.services.artefact_changes import notify_artefact_changed, requirement_content_changed
from app.services.custom_fields import validate_custom_field_values
from app.services.principals import principal_columns, principal_labels, principal_ref, validate_principal
from app.services.rbac import lock_project_for_update, lock_row_for_update

# C-G-11: completion is an overlay marker on top of APPROVED, not a
# separate lifecycle status a requirement can be "in" — a completed
# requirement's status is still APPROVED (see `Requirement.is_completed`),
# so this set no longer needs a second member to cover it.
LOCKED_STATUSES = {RequirementStatus.APPROVED}


def get_current_version(db: Session, requirement_id: UUID) -> RequirementVersion:
    """Returns the current (valid_to IS NULL) version row for a requirement."""
    version = db.scalar(
        select(RequirementVersion).where(
            RequirementVersion.requirement_id == requirement_id, RequirementVersion.valid_to.is_(None)
        )
    )
    if version is None:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Requirement has no current version.")
    return version


def get_current_version_for_update(db: Session, requirement_id: UUID) -> RequirementVersion:
    """`get_current_version` after locking the requirement row, for every path that
    writes a next version: a second concurrent edit waits for the first, then reads
    the version the first created instead of dying on the
    `(requirement_id, version_number)` unique constraint (see `lock_row_for_update`).
    The lock must precede the read, which is why the two are one call.

    Raises:
        HTTPException: 500 if the requirement has no current version.
    """
    lock_row_for_update(db, Requirement, requirement_id)
    return get_current_version(db, requirement_id)


def is_locked(version: RequirementVersion) -> bool:
    """Whether a requirement version can only change via an approved change request (C-G-12)."""
    return version.status in LOCKED_STATUSES


def requires_change_request_for_links(db: Session, project: Project) -> bool:
    """Whether `project` requires an approved change request to add/remove a
    requirement-to-requirement traceability `ArtefactLink` on an
    already-approved requirement (a
    deliberately narrower, opt-in sibling of C-G-12's unconditional lock on
    a requirement's own content fields; traceability links otherwise stay
    ungated by design, see `models.relationship.ArtefactLink`'s docstring).

    Resolution order, per the confirmed design (docs/decisions.md):
      1. The project's own opt-in toggle
         (`Project.require_change_request_for_approved_links`) always wins
         when set — a project may lock itself down regardless of any org
         policy.
      2. Otherwise, the organisation's own force-on policy
         (`Organization.force_require_change_request_for_approved_links`)
         applies to every project in the org *except* one explicitly marked
         `Project.exempt_from_org_link_lock` — the org's one narrow escape
         hatch for a project that genuinely needs the permissive default
         despite the org-wide policy.
      3. Otherwise (neither set), links remain ungated — the pre-existing,
         default-permissive behaviour.

    Callers still separately check `is_locked(version)` — this function
    only answers "does this project's policy require a change request *for
    an already-locked requirement's links*", not whether the requirement is
    locked at all (an unlocked requirement's links are never gated,
    regardless of this policy).
    """
    if project.require_change_request_for_approved_links:
        return True
    org = db.get(Organization, project.organization_id)
    if org is None:
        return False
    return org.force_require_change_request_for_approved_links and not project.exempt_from_org_link_lock


def _next_sequence(db: Session, project: Project) -> int:
    """Returns the next requirement sequence number for `project`, advancing
    the counter so it is never reused (C-G-06), including for archived
    requirements.

    Locks the project row and re-reads the counter first (2026-10-05): two
    concurrent creates in one project each read the same value and the
    second failed on the unique `(project_id, unique_code)` constraint with
    a 500 — the same race `services.sequences` already closes this way.
    """
    lock_project_for_update(db, project.id)
    db.refresh(project, attribute_names=["next_requirement_seq"])
    seq = project.next_requirement_seq
    project.next_requirement_seq = seq + 1
    return seq


def generate_unique_code(db: Session, project: Project, component: ProjectComponent, category: ProjectCategory) -> str:
    """Builds a unique, never-reused requirement identifier (C-G-06, C-G-07)."""
    seq = _next_sequence(db, project)
    return f"{component.prefix}-{category.prefix}-{seq:03d}"


def version_people(db: Session, versions: Iterable[RequirementVersion]) -> dict[tuple[str, UUID], PrincipalOut]:
    """Display data for the owner and reviewer of every version in `versions`, in one batch, keyed by
    `(type, id)` (`services.principals.principal_labels`)."""
    refs = []
    for version in versions:
        refs.append(principal_ref(version.owner_type, version.owner_id))
        refs.append(principal_ref(version.reviewer_type, version.reviewer_id))
    return principal_labels(db, refs)


def create_requirement(
    db: Session,
    project: Project,
    component: ProjectComponent,
    category: ProjectCategory,
    creator: User,
    *,
    name: str,
    reasoning: str,
    clarification: str,
    description: str = "",
    owner: PrincipalRef | None,
    keywords: list[str],
    sort_order: int,
    target_stage_id: UUID,
    level: RequirementLevel = RequirementLevel.REQUIREMENT,
    custom_fields: dict[str, Any] | None = None,
    creator_override_id: UUID | None = None,
    review_date: date | None = None,
    review_lead_days: int | None = None,
    reviewer: PrincipalRef | None = None,
) -> Requirement:
    """Creates a requirement and its initial (version 1) content snapshot.

    Args:
        creator: The user actually performing the API call (recorded as
            `version.created_by` for audit integrity).
        creator_override_id: If set (only honoured for callers who have
            already verified the acting user is a project manager), this
            becomes `requirement.creator_id` instead of `creator.id` — lets
            a PM re-attribute authorship at creation time (C-A-11) without
            falsifying the audit trail of who technically made the request.
        owner: The responsible principal (the caller has validated it); the creator when omitted.
        reviewer: The principal accountable for the scheduled review, or None.
    """
    unique_code = generate_unique_code(db, project, component, category)
    requirement = Requirement(
        project_id=project.id, component_id=component.id, category_id=category.id,
        unique_code=unique_code, creator_id=creator_override_id or creator.id,
    )
    db.add(requirement)
    db.flush()

    now = datetime.now(UTC)
    version = RequirementVersion(
        requirement_id=requirement.id, version_number=1, valid_from=now, valid_to=None,
        name=name, reasoning=reasoning, clarification=clarification, description=description,
        status=RequirementStatus.DRAFT,
        **principal_columns("owner", owner or PrincipalRef(type=PrincipalType.USER, id=creator.id)),
        target_stage_id=target_stage_id, level=level,
        sort_order=sort_order, created_by=creator.id, created_at=now,
        change_note="Initial creation.", custom_fields=custom_fields or {},
        review_date=review_date, review_lead_days=review_lead_days, **principal_columns("reviewer", reviewer),
    )
    db.add(version)

    if keywords:
        tag_service.set_keywords(db, requirement, keywords, creator.id)

    return requirement


def apply_new_version(
    db: Session,
    requirement: Requirement,
    current_version: RequirementVersion,
    actor: User,
    *,
    name: str | None = None,
    reasoning: str | None = None,
    clarification: str | None = None,
    description: str | None = None,
    status_value: RequirementStatus | None = None,
    owner: PrincipalRef | None = None,
    target_stage_id: UUID | None = None,
    target_stage_explicitly_set: bool = False,
    level: RequirementLevel | None = None,
    change_note: str = "",
    change_request_id: UUID | None = None,
    custom_fields: dict[str, Any] | None = None,
    review_date: date | None = None,
    review_date_explicitly_set: bool = False,
    review_lead_days: int | None = None,
    review_lead_days_explicitly_set: bool = False,
    reviewer: PrincipalRef | None = None,
    reviewer_explicitly_set: bool = False,
) -> RequirementVersion:
    """Closes the current version and inserts a new one with the given changes.

    Any field left as None carries over the current version's value
    unchanged, so callers only need to specify what is actually changing.
    `target_stage_id` (and, per C-R-06, the review-scheduling fields) are
    nullable in the schema, so their `*_explicitly_set` flags disambiguate
    "clear this field" (pass the value as None with the flag True) from
    "leave it unchanged" (the flag stays False).

    `owner` and `reviewer` are principals (the caller has validated them); `reviewer`, like the other
    nullable fields, is cleared by passing None with `reviewer_explicitly_set`.

    `review_reminder_sent_at` always resets to unset on a new version — it's
    tied to whatever `review_date` this version carries, and any version
    change is a safe point to re-arm the reminder rather than risk silently
    carrying forward a "reminder already sent" flag for a date that may no
    longer even be the same review target.

    When the new version changes what the requirement says (name, description,
    reasoning, clarification or level), or moves it to `ARCHIVED`, every module's
    `on_artefact_changed` hook is told (`services.artefact_changes`), so anything
    that depends on the requirement can be flagged for review.
    """
    now = datetime.now(UTC)
    current_version.valid_to = now

    new_version = RequirementVersion(
        requirement_id=requirement.id,
        version_number=current_version.version_number + 1,
        valid_from=now,
        valid_to=None,
        name=name if name is not None else current_version.name,
        reasoning=reasoning if reasoning is not None else current_version.reasoning,
        clarification=clarification if clarification is not None else current_version.clarification,
        description=description if description is not None else current_version.description,
        status=status_value if status_value is not None else current_version.status,
        **(
            principal_columns("owner", owner) if owner is not None
            else {"owner_type": current_version.owner_type, "owner_id": current_version.owner_id}
        ),
        target_stage_id=target_stage_id if target_stage_explicitly_set else current_version.target_stage_id,
        level=level if level is not None else current_version.level,
        approval_authority_id=actor.id if status_value == RequirementStatus.APPROVED else current_version.approval_authority_id,
        sort_order=current_version.sort_order,
        change_request_id=change_request_id,
        change_note=change_note,
        created_by=actor.id,
        created_at=now,
        custom_fields=custom_fields if custom_fields is not None else current_version.custom_fields,
        review_date=review_date if review_date_explicitly_set else current_version.review_date,
        review_lead_days=review_lead_days if review_lead_days_explicitly_set else current_version.review_lead_days,
        **(
            principal_columns("reviewer", reviewer) if reviewer_explicitly_set
            else {"reviewer_type": current_version.reviewer_type, "reviewer_id": current_version.reviewer_id}
        ),
        review_reminder_sent_at=None,
    )
    db.add(new_version)
    changed_fields = requirement_content_changed(current_version, new_version)
    if new_version.status == RequirementStatus.ARCHIVED and current_version.status != RequirementStatus.ARCHIVED:
        _announce_change(db, requirement, actor, "archived", "archived")
    elif changed_fields:
        _announce_change(db, requirement, actor, "content_changed", f"changed {', '.join(changed_fields)}")
    return new_version


def _announce_change(db: Session, requirement: Requirement, actor: User, kind: str, what: str) -> None:
    """Tells the modules a requirement changed (see `notify_artefact_changed`)."""
    notify_artefact_changed(db, ArtefactChange(
        artefact_type="requirement", artefact_id=requirement.id, project_id=requirement.project_id,
        kind=kind, summary=f"{requirement.unique_code} {what}", actor_id=actor.id,
    ))


def archive_requirement(db: Session, requirement: Requirement, actor: User) -> None:
    """Soft-archives a requirement, preserving its full version history (C-A-06),
    and tells the modules (a dependent may now rest on an archived requirement)."""
    requirement.is_archived = True
    requirement.archived_at = datetime.now(UTC)
    requirement.archived_by = actor.id
    _announce_change(db, requirement, actor, "archived", "archived")


def unarchive_requirement(db: Session, requirement: Requirement, actor: User) -> None:
    """Restores an archived requirement to the active list, undoing
    `archive_requirement`. Mirrors `routers.projects::unarchive_project`'s
    shape: unconditional (no already-active guard), so calling this on a
    requirement that isn't archived is a harmless no-op rather than an
    error — same idempotency contract the project endpoint already has.
    """
    requirement.is_archived = False
    requirement.archived_at = None
    requirement.archived_by = None


def set_keywords(db: Session, requirement: Requirement, keywords: list[str], actor_id: UUID | None = None) -> None:
    """Replaces a requirement's keyword set (C-M-01): its tags, under the project's tag mode.

    Raises:
        HTTPException: 422 for an invalid name, or one not on the list in a restricted project.
    """
    tag_service.set_keywords(db, requirement, keywords, actor_id)


def get_keywords(db: Session, requirement_id: UUID) -> list[str]:
    """The requirement's keywords (its tag names)."""
    return tag_service.get_keywords(db, requirement_id)


# --- list filtering (shared by the list endpoint and the record table export) ----------------------

OPEN_CR_STATUSES = (ChangeRequestStatus.SUBMITTED, ChangeRequestStatus.IN_REVIEW)
"""Change request statuses that count as "open" for a requirement's list badge."""


@dataclass
class ListPrefetch:
    """Per-requirement lookups for a whole list, loaded in a fixed number of
    queries (`prefetch_for_list`) instead of five per row — the list
    endpoint was the second-hottest backend path in the e2e suite (99
    queries for one page of Alpha-1, 2026-10-04 profiling).

    Attributes:
        versions: Current (`valid_to IS NULL`) version per requirement id.
        keywords: Keywords per requirement id (absent = none).
        subscribed: Requirement ids the caller is subscribed to.
        comment_counts: Comment count per requirement id (absent = 0).
        open_change_request: Requirement ids with an open change request.
        people: Resolved owner and reviewer (`services.principals.principal_labels`), keyed by `(type, id)`.
    """

    versions: dict[UUID, RequirementVersion] = field(default_factory=dict)
    keywords: dict[UUID, list[str]] = field(default_factory=dict)
    subscribed: set[UUID] = field(default_factory=set)
    comment_counts: dict[UUID, int] = field(default_factory=dict)
    open_change_request: set[UUID] = field(default_factory=set)
    people: dict[tuple[str, UUID], PrincipalOut] = field(default_factory=dict)


def prefetch_for_list(db: Session, requirement_ids: list[UUID], current_user_id: UUID) -> ListPrefetch:
    """Loads every `ListPrefetch` field for `requirement_ids` in a fixed number of queries.

    Raises:
        HTTPException: 500 if a requirement has no current version (the same
            broken-data signal `get_current_version` raises).
    """
    prefetch = ListPrefetch()
    if not requirement_ids:
        return prefetch
    for version in db.scalars(select(RequirementVersion).where(
        RequirementVersion.requirement_id.in_(requirement_ids), RequirementVersion.valid_to.is_(None),
    )).all():
        prefetch.versions[version.requirement_id] = version
    if len(prefetch.versions) != len(set(requirement_ids)):
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Requirement has no current version.")
    prefetch.people = version_people(db, prefetch.versions.values())
    prefetch.keywords = tag_service.keywords_for_requirements(db, requirement_ids)
    prefetch.subscribed = set(db.scalars(select(Subscription.entity_id).where(
        Subscription.subscriber_type == PrincipalType.USER.value, Subscription.subscriber_id == current_user_id,
        Subscription.entity_type == "requirement",
        Subscription.entity_id.in_(requirement_ids),
    )).all())
    prefetch.comment_counts = engagement.get_comment_counts(db, ReviewTargetType.REQUIREMENT, requirement_ids)
    prefetch.open_change_request = set(db.scalars(select(ChangeRequest.requirement_id).where(
        ChangeRequest.requirement_id.in_(requirement_ids), ChangeRequest.status.in_(OPEN_CR_STATUSES),
    )).all())
    return prefetch


@dataclass(frozen=True)
class RequirementFilters:
    """The requirement list's filters (the query parameters of `GET .../requirements`, minus paging and sort).

    Attributes mirror those parameters; `status` is the version status, `search` matches the name or code.
    """

    include_archived: bool = False
    is_completed: bool | None = None
    component_id: UUID | None = None
    category_id: UUID | None = None
    tag_names: tuple[str, ...] = ()
    tag_match_all: bool = False
    keyword: str | None = None
    search: str | None = None
    status: RequirementStatus | None = None
    target_stage_id: UUID | None = None
    has_comments: bool | None = None
    only_watched: bool | None = None


@dataclass(frozen=True)
class ListSortKeys:
    """The few current-version values the list needs to filter, order and sort every row of a project,
    read as columns so a large project is not loaded as whole versions (description text and all).

    Attributes:
        name: The version name.
        status: The version status.
        target_stage_id: The version's target stage.
        sort_order: The version's manual order within its category.
    """

    name: str
    status: RequirementStatus
    target_stage_id: UUID | None
    sort_order: int


@dataclass
class FilteredRequirements:
    """A project's requirements after `filter_requirements`.

    Attributes:
        requirements: The matching requirements, in component/category order when asked.
        prefetch: The lookups for exactly those rows (versions, people, counts); empty when the caller asked
            for none (`prefetch=False`) and will load them for the one page it returns.
        unfiltered: How many requirements the project has before any filter beyond archived visibility.
        sort_keys: `ListSortKeys` per kept requirement id.
    """

    requirements: list[Requirement]
    prefetch: ListPrefetch
    unfiltered: int
    sort_keys: dict[UUID, ListSortKeys] = field(default_factory=dict)


def filter_requirements(
    db: Session, project_id: UUID, current_user_id: UUID, filters: RequirementFilters, *, structural_order: bool,
    prefetch: bool = True,
) -> FilteredRequirements:
    """One project's requirements narrowed by `filters`: the single implementation behind the list endpoint
    and the record table export, so a filter added here reaches both.

    The project's rows are read as identity rows plus the current version's filter and order columns (one
    query); keywords, comment counts and subscriptions are loaded for the whole project only when a filter
    needs them. The full per-row lookups (`prefetch_for_list`) are then loaded for the **kept** rows only, or
    left to the caller (`prefetch=False`) when it returns just one page of them.

    Args:
        db: Active session (read only).
        project_id: The project.
        current_user_id: The caller (for `only_watched` and the subscription lookup).
        filters: The filters.
        structural_order: Order by the project's component, category and sort order (the list's default
            when no explicit sort is requested).
        prefetch: Load the per-row lookups for the kept rows (default); `False` returns an empty prefetch.

    Returns:
        The rows, their sort keys, their prefetched lookups (unless skipped) and the unfiltered count.

    Raises:
        HTTPException: 500 if a requirement has no current version (broken data).
    """
    query = select(Requirement).where(Requirement.project_id == project_id)
    if not filters.include_archived:
        query = query.where(Requirement.is_archived.is_(False))
    unfiltered = db.scalar(select(func.count()).select_from(query.subquery())) or 0

    if filters.is_completed is not None:
        query = query.where(Requirement.is_completed.is_(filters.is_completed))
    if filters.component_id:
        query = query.where(Requirement.component_id == filters.component_id)
    if filters.category_id:
        query = query.where(Requirement.category_id == filters.category_id)
    if any(t.strip() for t in filters.tag_names):
        query = query.where(Requirement.id.in_(
            tag_service.tagged_ids(
                db, project=db.get(Project, project_id), artefact_type="requirement",
                names=list(filters.tag_names), match_all=filters.tag_match_all,
            )
        ))
    rows = db.execute(
        query.add_columns(
            RequirementVersion.id, RequirementVersion.name, RequirementVersion.status,
            RequirementVersion.target_stage_id, RequirementVersion.sort_order,
        ).outerjoin(RequirementVersion, and_(
            RequirementVersion.requirement_id == Requirement.id, RequirementVersion.valid_to.is_(None),
        ))
    ).all()
    candidates = [row[0] for row in rows]
    if any(row[1] is None for row in rows):
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Requirement has no current version.")
    keys = {row[0].id: ListSortKeys(*row[2:]) for row in rows}
    ids = list(keys)

    keywords = tag_service.keywords_for_requirements(db, ids) if filters.keyword and ids else {}
    comment_counts = (
        engagement.get_comment_counts(db, ReviewTargetType.REQUIREMENT, ids) if filters.has_comments and ids else {}
    )
    subscribed = set(db.scalars(select(Subscription.entity_id).where(
        Subscription.subscriber_type == PrincipalType.USER.value, Subscription.subscriber_id == current_user_id,
        Subscription.entity_type == "requirement", Subscription.entity_id.in_(ids),
    )).all()) if filters.only_watched and ids else set()

    kept: list[Requirement] = []
    for req in candidates:
        key = keys[req.id]
        if filters.keyword and filters.keyword.casefold() not in {k.casefold() for k in keywords.get(req.id, [])}:
            continue
        if filters.search:
            needle = filters.search.lower()
            if needle not in key.name.lower() and needle not in req.unique_code.lower():
                continue
        if filters.status and key.status != filters.status:
            continue
        if filters.target_stage_id and key.target_stage_id != filters.target_stage_id:
            continue
        if filters.has_comments and comment_counts.get(req.id, 0) == 0:
            continue
        if filters.only_watched and req.id not in subscribed:
            continue
        kept.append(req)

    if structural_order:
        comp_order = {c.id: c.sort_order for c in db.scalars(
            select(ProjectComponent).where(ProjectComponent.project_id == project_id)).all()}
        cat_order = {c.id: c.sort_order for c in db.scalars(
            select(ProjectCategory).where(ProjectCategory.project_id == project_id)).all()}
        kept.sort(key=lambda r: (comp_order.get(r.component_id, 0), cat_order.get(r.category_id, 0), keys[r.id].sort_order))
    return FilteredRequirements(
        requirements=kept,
        prefetch=prefetch_for_list(db, [r.id for r in kept], current_user_id) if prefetch else ListPrefetch(),
        unfiltered=unfiltered,
        sort_keys={r.id: keys[r.id] for r in kept},
    )


# --- direct edit (shared by the edit endpoint and the record table import) -------------------------


def edit_requirement(
    db: Session,
    project: Project,
    requirement: Requirement,
    actor: User,
    *,
    name: str | None = None,
    reasoning: str | None = None,
    clarification: str | None = None,
    description: str | None = None,
    status_value: RequirementStatus | None = None,
    owner: PrincipalRef | None = None,
    target_stage_id: UUID | None = None,
    level: RequirementLevel | None = None,
    change_note: str = "",
    custom_fields: dict[str, Any] | None = None,
    review_date: date | None = None,
    review_date_explicitly_set: bool = False,
    review_lead_days: int | None = None,
    review_lead_days_explicitly_set: bool = False,
    reviewer: PrincipalRef | None = None,
    reviewer_explicitly_set: bool = False,
    component_id: UUID | None = None,
    category_id: UUID | None = None,
    keywords: list[str] | None = None,
) -> RequirementVersion:
    """A direct edit of a requirement: the version lock, validation and new version the edit endpoint applies.

    Every field left `None` is carried over from the current version (the nullable review fields and the
    reviewer use their `*_explicitly_set` flag to tell "clear" from "leave"). The caller has checked the actor's
    right to edit and writes the audit event and commits.

    Args:
        db: Active session.
        project: The requirement's project.
        requirement: The requirement.
        actor: The person editing.
        custom_fields: The **complete** custom field values to store (validated here), or `None` to keep them.
        component_id / category_id: Move the requirement (both given, the category inside the component).
        keywords: Replace the keyword set, or `None` to leave it.

    Returns:
        The new version.

    Raises:
        HTTPException: 409 when the requirement is approved (changes then go through a change request); 400/422
            for a custom field value, person, component or category that is not valid for the project.
    """
    current_version = get_current_version_for_update(db, requirement.id)
    if is_locked(current_version):
        raise HTTPException(status.HTTP_409_CONFLICT, "This requirement is approved; changes must be made via a change request.")
    validated = (
        validate_custom_field_values(db, project.id, CustomFieldEntityKind.REQUIREMENT, custom_fields)
        if custom_fields is not None else None
    )
    for person_field, person in (("owner", owner), ("reviewer", reviewer)):
        validate_principal(db, person, organization_id=project.organization_id, project_id=project.id, field=person_field)
    new_version = apply_new_version(
        db, requirement, current_version, actor,
        name=name, reasoning=reasoning, clarification=clarification, description=description,
        status_value=status_value, owner=owner,
        target_stage_id=target_stage_id, target_stage_explicitly_set=target_stage_id is not None,
        level=level, change_note=change_note, custom_fields=validated,
        review_date=review_date, review_date_explicitly_set=review_date_explicitly_set,
        review_lead_days=review_lead_days, review_lead_days_explicitly_set=review_lead_days_explicitly_set,
        reviewer=reviewer, reviewer_explicitly_set=reviewer_explicitly_set,
    )
    if component_id is not None and category_id is not None and (
        component_id != requirement.component_id or category_id != requirement.category_id
    ):
        component = db.get(ProjectComponent, component_id)
        category = db.get(ProjectCategory, category_id)
        if component is None or component.project_id != project.id or category is None or category.project_id != project.id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid component or category.")
        if category.component_id != component.id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Category does not belong to the selected component.")
        requirement.component_id = component_id
        requirement.category_id = category_id
    if keywords is not None:
        set_keywords(db, requirement, keywords, actor.id)
    return new_version
