"""
Module: services.requirements

Core requirement business logic: unique ID generation (C-G-06, C-G-07),
versioned content changes (C-A-02), the change-request-only edit lock once a
requirement is approved (C-G-12), archival (C-A-06), and keyword/traceability
management (C-M-01, C-G-09).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Any, Literal
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import ColumnElement, String, and_, case, cast, exists, func, or_, select
from sqlalchemy.orm import Session

from app.models.change_request import ChangeRequest, ReviewComment
from app.models.custom_field import CustomFieldEntityKind
from app.models.engagement import Subscription
from app.models.enums import (
    ChangeRequestStatus,
    PrincipalType,
    ProjectRole,
    RequirementLevel,
    RequirementStatus,
    ReviewTargetType,
)
from app.models.organization import Organization
from app.models.project import Project, ProjectCategory, ProjectComponent, ProjectStage
from app.models.requirement import Requirement, RequirementVersion
from app.models.requirement_alias import RequirementAlias
from app.models.requirement_type import ProjectRequirementType, RequirementTypeDefinition
from app.models.user import User
from app.modules.registry import ArtefactChange
from app.schemas.principal import PrincipalOut, PrincipalRef
from app.services import component_stages, engagement
from app.services import tags as tag_service
from app.services.artefact_changes import notify_artefact_changed, requirement_content_changed
from app.services.custom_fields import validate_custom_field_values
from app.services.external_reference_surfaces import reference_clause
from app.services.list_sort import apply_direction, code_order_columns, instant, text_order_column
from app.services.lookups import present, project_or_404
from app.services.principals import principal_columns, principal_labels, principal_ref, validate_principal
from app.services.rbac import lock_project_for_update, lock_row_for_update
from app.services.requirement_types import matching_type_row_ids, resolve_requirement_type
from app.services.requirement_types import type_names as requirement_type_names

if TYPE_CHECKING:
    from app.services.placements import PlacementPair

# The project roles that may edit a requirement (a status change to Approved additionally needs the manager role).
CAN_EDIT_ROLES = (ProjectRole.PROJECT_MANAGER, ProjectRole.PROJECT_ADMINISTRATOR, ProjectRole.STAKEHOLDER)

# C-G-11: completion is an overlay marker on APPROVED (`Requirement.is_completed`), not a separate status,
# so a completed requirement is still APPROVED and this set has one member.
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
    """Returns the next requirement sequence number for `project`, advancing the counter so it is never reused
    (C-G-06), including for archived requirements.

    Locks the project row and re-reads the counter first, so concurrent creates cannot take the same value
    (the same lock `services.sequences` uses).
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


def resolve_type_or_422(db: Session, project: Project, type_id: UUID | None) -> UUID | None:
    """`services.requirement_types.resolve_requirement_type` for a request: the project type row to store.

    Raises:
        HTTPException: 422 when `type_id` is not an enabled requirement type of the project.
    """
    try:
        return resolve_requirement_type(db, project, type_id)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc


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
    type_id: UUID | None = None,
    project_type_id: UUID | None = None,
    unique_code: str | None = None,
    change_note: str = "Initial creation.",
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
        type_id: The requirement type chosen from the project's list (`services.requirement_types`), or None.
        project_type_id: A project type row already stored on another requirement (a copy keeps the original's type
            even when the project has since disabled it); used when `type_id` is not given.
        unique_code: A code already issued for this requirement (an alias code taken over when the alias is made
            independent); a fresh code is numbered from the project counter when omitted.
        change_note: The first version's note.
    """
    if review_date is not None:
        check_review_date_policy(db, project.id, review_date)
    project_type_id = resolve_type_or_422(db, project, type_id) if type_id is not None else project_type_id
    unique_code = unique_code or generate_unique_code(db, project, component, category)
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
        target_stage_id=target_stage_id, level=level, project_type_id=project_type_id,
        sort_order=sort_order, created_by=creator.id, created_at=now,
        change_note=change_note, custom_fields=custom_fields or {},
        review_date=review_date, review_lead_days=review_lead_days, **principal_columns("reviewer", reviewer),
    )
    db.add(version)

    if keywords:
        tag_service.set_keywords(db, requirement, keywords, creator.id)

    return requirement


def check_status_move(
    db: Session, project_id: UUID, requirement_id: UUID, current: RequirementStatus, target: RequirementStatus,
) -> None:
    """Refuses a status move the project's requirement lifecycle does not allow.

    A move to the status the requirement already has is not a move. The lifecycle is the engine's
    (`services.lifecycles.check_move`): the path, the states the project turned off, the states the organisation
    requires and an explicit request to skip steps.

    Args:
        db: Active session (a skip writes one audit event; not committed).
        project_id: The requirement's project.
        requirement_id: The requirement.
        current: Its current status.
        target: The status it is moved to.

    Raises:
        HTTPException: 409 naming the allowed next states when the move is not legal here; 403 when a skip passes over
            a step the person may not enter.
    """
    from app.services.lifecycles import check_move

    if current == target:
        return
    try:
        check_move(db, project_id, "requirement", current.value, target.value, record_id=requirement_id)
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc


def check_review_date_policy(db: Session, project_id: UUID, review_date: date) -> None:
    """Refuses a review date later than the project's review policy allows.

    The policy's interval is the longest gap between two reviews, so a review date a person sets may be no later than
    that many days from the caller's day. No interval, no cap.

    Args:
        db: Active session (read only).
        project_id: The requirement's project.
        review_date: The review date being set.

    Raises:
        HTTPException: 422 naming the latest allowed date.
    """
    from app.services import review_engine
    from app.services.client_date import effective_today

    today = effective_today()
    try:
        review_engine.check_next_review_date(review_engine.review_policy(db, project_id, "requirement"), today, review_date)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc


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
    project_type_id: UUID | None = None,
    project_type_explicitly_set: bool = False,
) -> RequirementVersion:
    """Closes the current version and inserts a new one with the given changes.

    Any field left as None carries over the current version's value
    unchanged, so callers only need to specify what is actually changing.
    `target_stage_id` (and, per C-R-06, the review-scheduling fields) are
    nullable in the schema, so their `*_explicitly_set` flags disambiguate
    "clear this field" (pass the value as None with the flag True) from
    "leave it unchanged" (the flag stays False). `project_type_id` is a project type row (resolve a payload's id with
    `resolve_type_or_422` first) and follows the same flag rule.

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
    if review_date_explicitly_set and review_date is not None and review_date != current_version.review_date:
        check_review_date_policy(db, requirement.project_id, review_date)
    now = datetime.now(UTC)
    current_version.valid_to = now
    requirement.updated_at = now  # a new version is a change to the record: its Modified time moves

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
        project_type_id=project_type_id if project_type_explicitly_set else current_version.project_type_id,
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


def _announce_change(
    db: Session, requirement: Requirement, actor: User, kind: Literal["content_changed", "archived"], what: str,
) -> None:
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
    """Per-requirement lookups for a whole list, loaded in a fixed number of queries (`prefetch_for_list`) instead of
    five per row.

    Attributes:
        versions: Current (`valid_to IS NULL`) version per requirement id.
        keywords: Keywords per requirement id (absent = none).
        subscribed: Requirement ids the caller is subscribed to.
        comment_counts: Comment count per requirement id (absent = 0).
        open_change_request: Requirement ids with an open change request.
        people: Resolved owner and reviewer (`services.principals.principal_labels`), keyed by `(type, id)`.
        aliases: Active aliases per requirement id (absent = none).
        type_names: The requirement type name per project type row id the versions reference.
    """

    versions: dict[UUID, RequirementVersion] = field(default_factory=dict)
    keywords: dict[UUID, list[str]] = field(default_factory=dict)
    subscribed: set[UUID] = field(default_factory=set)
    comment_counts: dict[UUID, int] = field(default_factory=dict)
    open_change_request: set[UUID] = field(default_factory=set)
    people: dict[tuple[str, UUID], PrincipalOut] = field(default_factory=dict)
    aliases: dict[UUID, list[RequirementAlias]] = field(default_factory=dict)
    type_names: dict[UUID, str] = field(default_factory=dict)


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
    prefetch.type_names = requirement_type_names(db, [v.project_type_id for v in prefetch.versions.values()])
    prefetch.keywords = tag_service.keywords_for_requirements(db, requirement_ids)
    for alias in db.scalars(
        select(RequirementAlias)
        .where(RequirementAlias.requirement_id.in_(requirement_ids), RequirementAlias.is_retired.is_(False))
        .order_by(RequirementAlias.created_at, RequirementAlias.unique_code)
    ):
        prefetch.aliases.setdefault(alias.requirement_id, []).append(alias)
    prefetch.subscribed = set(db.scalars(select(Subscription.entity_id).where(
        Subscription.subscriber_type == PrincipalType.USER.value, Subscription.subscriber_id == current_user_id,
        Subscription.entity_type == "requirement",
        Subscription.entity_id.in_(requirement_ids),
    )).all())
    prefetch.comment_counts = engagement.get_comment_counts(db, ReviewTargetType.REQUIREMENT, requirement_ids)
    prefetch.open_change_request = set(present(db.scalars(select(ChangeRequest.requirement_id).where(
        ChangeRequest.requirement_id.in_(requirement_ids), ChangeRequest.status.in_(OPEN_CR_STATUSES),
    )).all()))
    return prefetch


@dataclass(frozen=True)
class RequirementFilters:
    """The requirement list's filters (the query parameters of `GET .../requirements`, minus paging and sort).

    Attributes mirror those parameters; `status` is the version status, `search` matches the name or code.
    `target_stage_from_id`/`target_stage_to_id` bound the target stage by the stages' order (a stage's
    position in the project, never its name); either end may be left open, and a stage that is not one of
    the project's matches nothing. `phase` keeps the requirements whose governing phase (their component's track
    when component phases are on, else the stage's) has this name.
    """

    include_archived: bool = False
    is_completed: bool | None = None
    component_ids: tuple[UUID, ...] = ()
    category_ids: tuple[UUID, ...] = ()
    tag_names: tuple[str, ...] = ()
    tag_match_all: bool = False
    external_systems: tuple[str, ...] = ()
    external_key: str | None = None
    type_names: tuple[str, ...] = ()
    keyword: str | None = None
    search: str | None = None
    status: RequirementStatus | None = None
    target_stage_id: UUID | None = None
    target_stage_from_id: UUID | None = None
    target_stage_to_id: UUID | None = None
    has_comments: bool | None = None
    only_watched: bool | None = None
    phase: str | None = None


@dataclass
class ListRow:
    """A requirement as the list filters, orders and pages it: plain values read as columns, no ORM entity,
    so a project of 20,000 is a list of small objects rather than 20,000 mapped instances. Only one UUID column
    is read per row (the id): turning a UUID cell into a Python object costs more than the query, so the
    stage filter and the component/category order are applied in SQL instead of read back.

    Attributes:
        id / project_id / unique_code / created_at / updated_at: The identity row's values (`project_id` is the project
            asked for).
        name / status / sort_order: The current version's values the list filters and orders by.
        order_value: The value of the `ROW_ORDER_COLUMNS` sort asked for (`target`, `placement`), read with the row so a
            list widened over several projects orders the same way the database does; `None` for any other sort.
        from_project_id / from_project_name / from_project_code: Set by `ProjectScope.collect` on a row of
            another project.
    """

    id: UUID
    project_id: UUID
    unique_code: str
    created_at: datetime
    updated_at: datetime
    name: str
    status: RequirementStatus
    sort_order: int
    from_project_id: UUID | None = None
    from_project_name: str | None = None
    from_project_code: str | None = None
    order_value: Any = None


@dataclass
class FilteredRows:
    """A project's requirement rows after `filter_requirement_rows`.

    Attributes:
        rows: The matching rows (the requested page when `limit` was given), in the requested order.
        total: How many rows match the filters, before paging.
        unfiltered: How many requirements the project has before any filter beyond archived visibility.
    """

    rows: list[ListRow]
    total: int
    unfiltered: int


@dataclass
class FilteredRequirements:
    """A project's requirements after `filter_requirements`.

    Attributes:
        requirements: The matching requirements, in component/category order when asked.
        prefetch: The lookups for exactly those rows (versions, people, counts); empty when the caller asked
            for none (`prefetch=False`).
        unfiltered: How many requirements the project has before any filter beyond archived visibility.
    """

    requirements: list[Requirement]
    prefetch: ListPrefetch
    unfiltered: int


def _stage_range(db: Session, project_id: UUID, filters: RequirementFilters) -> set[UUID] | None:
    """The ids of the project's stages between the filter's two ends, or `None` when no range is asked for.

    Args:
        db: Active session (read only).
        project_id: The project whose stages are ordered.
        filters: The filters; only the two stage range ends are read.

    Returns:
        The stage ids from the first end to the last by `sort_order` (inclusive; an open end reaches the
        first or last stage). An end that is not one of the project's stages gives the empty set, so a
        related project's rows never match a stage of another project.
    """
    if filters.target_stage_from_id is None and filters.target_stage_to_id is None:
        return None
    stages = db.scalars(select(ProjectStage).where(ProjectStage.project_id == project_id)).all()
    # Order by position with the id as a tie-break so the range never depends on row order.
    ordered = sorted(stages, key=lambda s: (s.sort_order, str(s.id)))
    index = {s.id: i for i, s in enumerate(ordered)}
    ends = [e for e in (filters.target_stage_from_id, filters.target_stage_to_id) if e is not None]
    if any(e not in index for e in ends):
        return set()
    low = index[filters.target_stage_from_id] if filters.target_stage_from_id is not None else 0
    high = index[filters.target_stage_to_id] if filters.target_stage_to_id is not None else len(ordered) - 1
    return {s.id for s in ordered[low:high + 1]}


LIST_SORT_COLUMNS = ("unique_code", "name", "status", "created_at", "updated_at")
"""The columns `GET .../requirements?sort=` accepts, in the list's own names (`services.list_sort.KEY_ALIASES` also
lets a caller write `code`, `title`, `created` and `modified`)."""

#: The list's canonical sort keys (`services.list_sort`) in `LIST_SORT_COLUMNS`' names.
_CANONICAL_TO_COLUMN = {"code": "unique_code", "title": "name", "created": "created_at", "modified": "updated_at"}


#: Sorts whose value comes from tables the row query joins (the target stage, the component and category), read as
#: `ListRow.order_value`; `references` is ordered by the caller from the references' text (`ROW_TEXT_SORTS`).
ROW_ORDER_COLUMNS = ("target", "placement", "type")
ROW_TEXT_SORTS = ("references",)
"""The extra keys `GET .../requirements?sort=` accepts: `target` (the target stage's position, then the level), `placement`
(the component's then the category's name), `type` (the requirement type's rank, then its place in the list, then its name;
unranked types after ranked ones and an untyped requirement last) and `references` (the first external reference's system and key)."""

_LEVEL_RANK = case(
    (RequirementVersion.level == RequirementLevel.REQUIREMENT, 0),
    (RequirementVersion.level == RequirementLevel.RECOMMENDED, 1),
    else_=2,
)


def _row_order_expression(sort: str | None) -> ColumnElement[Any] | None:
    """The SQL value behind a `ROW_ORDER_COLUMNS` sort, or `None` for any other sort: the target stage's position times
    ten plus the level's rank (mandatory, recommended, optional), or the component name and category name, lower-cased
    and joined by a control character that sorts before any letter."""
    if sort == "target":
        return ProjectStage.sort_order * 10 + _LEVEL_RANK
    if sort == "placement":
        return func.lower(ProjectComponent.name) + "\x01" + func.lower(ProjectCategory.name)
    if sort == "type":
        rank = func.coalesce(ProjectRequirementType.rank, RequirementTypeDefinition.rank)
        position = func.coalesce(ProjectRequirementType.display_order_override, RequirementTypeDefinition.sort_order)
        name = func.coalesce(ProjectRequirementType.name_override, RequirementTypeDefinition.name)
        # An unranked type sorts after every ranked one, and an untyped requirement after every typed one.
        return func.coalesce(
            func.lpad(cast(func.coalesce(rank, 999999), String), 6, "0") + "\x01"
            + func.lpad(cast(position, String), 6, "0") + "\x01" + func.lower(name),
            "\x7f",
        )
    return None


def list_sort_column(sort: str | None) -> str | None:
    """`sort` as one of `LIST_SORT_COLUMNS` (a canonical key such as `title` is translated), or `None` when it is neither."""
    if sort is None:
        return None
    column = _CANONICAL_TO_COLUMN.get(sort, sort)
    return column if column in LIST_SORT_COLUMNS else None


def list_row_sort_value(row: ListRow, column: str) -> Any:
    """The value a `ListRow` is ordered by for `column` (one of `LIST_SORT_COLUMNS` or `ROW_ORDER_COLUMNS`): the order a
    widened scope applies in Python after joining several projects' rows, the same as the database's order for one project."""
    if column in ROW_ORDER_COLUMNS:
        return row.order_value
    if column == "status":
        return row.status.value
    if column in ("created_at", "updated_at"):
        return instant(getattr(row, column))
    return getattr(row, column)


def _sql_order(sort: str | None, descending: bool) -> list:
    """The ORDER BY for a list: the project's component, category and manual order when `sort` is None, else one
    column. Text is ordered by its lower-cased bytes (`COLLATE "C"`, the same order as Python's `str.lower()`
    comparison), never the database's locale, so the order does not depend on the server's collation, and a code by
    its prefix and then its number (`REQ-2` before `REQ-10`). The creation time and id break ties so a page is stable."""
    keys: list[Any]
    column_key = list_sort_column(sort)
    row_order = _row_order_expression(sort)
    if row_order is not None:
        keys = apply_direction([row_order.collate("C") if sort in ("placement", "type") else row_order], descending)
    elif column_key is None:
        keys = [ProjectComponent.sort_order, ProjectCategory.sort_order, RequirementVersion.sort_order]
    else:
        columns: Any = {
            "unique_code": code_order_columns(Requirement.unique_code),
            "name": [text_order_column(RequirementVersion.name)],
            "status": [cast(RequirementVersion.status, String).collate("C")],
            "created_at": [Requirement.created_at],
            "updated_at": [Requirement.updated_at],
        }[column_key]
        keys = apply_direction(columns, descending)
    return [*keys, Requirement.created_at, Requirement.id]


def _alias_clause(*where: ColumnElement[bool]) -> ColumnElement[bool]:
    """An EXISTS over the requirement's active aliases that satisfy `where` (a component or category match)."""
    return exists().where(RequirementAlias.requirement_id == Requirement.id, RequirementAlias.is_retired.is_(False), *where)


def filter_requirement_rows(
    db: Session, project_id: UUID, current_user_id: UUID, filters: RequirementFilters, *,
    sort: str | None = None, descending: bool = False, limit: int | None = None, offset: int = 0,
) -> FilteredRows:
    """One project's requirements narrowed by `filters`, ordered and optionally paged, as plain rows: the single
    implementation behind the list endpoint and the record table export, so a filter added here reaches both.

    The database applies every filter, the order and the page; one query returns only the rows asked for, with
    one UUID column each (turning a UUID cell into a Python object costs more than the query). The one exception
    is `filters.keyword`, which needs tag names: it narrows in Python, after the rows are read. Nothing is
    loaded per row; a caller loads the full records for the page it returns (`requirements_by_ids`,
    `prefetch_for_list`).

    Args:
        db: Active session (read only).
        project_id: The project.
        current_user_id: The caller (for `only_watched`).
        filters: The filters.
        sort: One of `LIST_SORT_COLUMNS`, or None for the project's component, category and manual order.
        descending: Reverse a column sort.
        limit: Return only this many rows (after `offset`); None returns all matching.
        offset: Rows to skip.

    Returns:
        The rows, the matching total and the unfiltered count.

    Raises:
        HTTPException: 500 if a requirement has no current version (broken data).
    """
    conditions = [Requirement.project_id == project_id]
    if not filters.include_archived:
        conditions.append(Requirement.is_archived.is_(False))
    unfiltered = db.scalar(select(func.count()).select_from(Requirement).where(*conditions)) or 0

    if filters.is_completed is not None:
        conditions.append(Requirement.is_completed.is_(filters.is_completed))
    # A requirement also sits in the places of its aliases, so a component or category filter matches those too.
    # Several ids match as every other record list's placement filter does: a requirement in any listed component or
    # any listed category.
    if filters.component_ids or filters.category_ids:
        places: list[ColumnElement[bool]] = []
        if filters.component_ids:
            places.append(Requirement.component_id.in_(filters.component_ids))
            places.append(_alias_clause(RequirementAlias.component_id.in_(filters.component_ids)))
        if filters.category_ids:
            places.append(Requirement.category_id.in_(filters.category_ids))
            places.append(_alias_clause(RequirementAlias.category_id.in_(filters.category_ids)))
        conditions.append(or_(*places))
    if any(t.strip() for t in filters.tag_names):
        conditions.append(Requirement.id.in_(
            tag_service.tagged_ids(
                db, project=project_or_404(db, project_id), artefact_type="requirement",
                names=list(filters.tag_names), match_all=filters.tag_match_all,
            )
        ))
    if filters.external_systems or filters.external_key:
        conditions.append(reference_clause(
            db, project_or_404(db, project_id).organization_id, "requirement", Requirement.id,
            filters.external_systems, filters.external_key,
        ))
    if filters.type_names:
        conditions.append(RequirementVersion.project_type_id.in_(matching_type_row_ids(db, project_id, filters.type_names)))
    if filters.target_stage_id:
        conditions.append(RequirementVersion.target_stage_id == filters.target_stage_id)
    stage_range = _stage_range(db, project_id, filters)
    if stage_range is not None:
        conditions.append(RequirementVersion.target_stage_id.in_(stage_range))
    if filters.phase and filters.phase.strip():
        conditions.append(component_stages.requirement_phase_clause(db, project_or_404(db, project_id), filters.phase))
    if filters.status:
        conditions.append(RequirementVersion.status == filters.status)
    if filters.search:
        needle = filters.search.lower()
        conditions.append(or_(
            func.strpos(func.lower(RequirementVersion.name), needle) > 0,
            func.strpos(func.lower(Requirement.unique_code), needle) > 0,
            exists().where(
                RequirementAlias.requirement_id == Requirement.id,
                func.strpos(func.lower(RequirementAlias.unique_code), needle) > 0,
            ),
        ))
    if filters.has_comments:
        conditions.append(exists().where(
            ReviewComment.target_type == ReviewTargetType.REQUIREMENT, ReviewComment.target_id == Requirement.id,
        ))
    if filters.only_watched:
        conditions.append(exists().where(
            Subscription.subscriber_type == PrincipalType.USER.value, Subscription.subscriber_id == current_user_id,
            Subscription.entity_type == "requirement", Subscription.entity_id == Requirement.id,
        ))

    def joined(query):
        query = query.outerjoin(RequirementVersion, and_(
            RequirementVersion.requirement_id == Requirement.id, RequirementVersion.valid_to.is_(None),
        ))
        if list_sort_column(sort) is None:
            query = query.join(ProjectComponent, ProjectComponent.id == Requirement.component_id).join(
                ProjectCategory, ProjectCategory.id == Requirement.category_id,
            )
        if sort == "target":
            query = query.outerjoin(ProjectStage, ProjectStage.id == RequirementVersion.target_stage_id)
        if sort == "type":
            query = query.outerjoin(
                ProjectRequirementType, ProjectRequirementType.id == RequirementVersion.project_type_id,
            ).outerjoin(RequirementTypeDefinition, RequirementTypeDefinition.id == ProjectRequirementType.org_type_id)
        return query.where(*conditions)

    def matching_count() -> int:
        """How many requirements match, counted from the requirement table alone unless a filter reads the version
        (status, stage, text): the version and the component and category joins only order and label the page."""
        query = select(func.count()).select_from(Requirement)
        if (
            filters.status or filters.target_stage_id or stage_range is not None or filters.search or filters.phase
            or filters.type_names
        ):
            query = query.outerjoin(RequirementVersion, and_(
                RequirementVersion.requirement_id == Requirement.id, RequirementVersion.valid_to.is_(None),
            ))
        return db.scalar(query.where(*conditions)) or 0

    # A keyword narrows in Python, so the page is cut after it; every other filter is already in the query.
    paged_in_sql = not filters.keyword
    row_order = _row_order_expression(sort)
    columns: list[Any] = [
        Requirement.id, Requirement.unique_code, Requirement.created_at, Requirement.updated_at,
        RequirementVersion.name, RequirementVersion.status, RequirementVersion.sort_order,
    ]
    query = joined(select(*columns, *([row_order] if row_order is not None else []))).order_by(*_sql_order(sort, descending))
    if paged_in_sql and limit is not None:
        query = query.limit(limit).offset(offset)
    rows = [
        ListRow(
            row[0], project_id, row[1], row[2], row[3], row[4], row[5], row[6],
            order_value=row[7] if row_order is not None else None,
        )
        for row in db.execute(query).all()
    ]
    if any(row.status is None for row in rows):
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Requirement has no current version.")
    if paged_in_sql:
        # Every row, or a page that did not fill (and is not past the end), already says how many there are: no second
        # query to count them.
        if limit is None:
            total = len(rows)
        elif len(rows) < limit and (rows or offset == 0):
            total = offset + len(rows)
        else:
            total = matching_count()

    if not paged_in_sql:
        keywords = tag_service.keywords_for_requirements(db, [row.id for row in rows]) if rows else {}
        wanted = (filters.keyword or "").casefold()  # not paged in SQL means a keyword was given
        rows = [row for row in rows if wanted in {k.casefold() for k in keywords.get(row.id, [])}]
        total = len(rows)
        if limit is not None:
            rows = rows[offset:offset + limit]
    return FilteredRows(rows=rows, total=total, unfiltered=unfiltered)


def requirements_by_ids(db: Session, ids: list[UUID]) -> list[Requirement]:
    """The requirements with these ids, in the order given (an unknown id is skipped)."""
    if not ids:
        return []
    found = {r.id: r for r in db.scalars(select(Requirement).where(Requirement.id.in_(ids)))}
    return [found[i] for i in ids if i in found]


def filter_requirements(
    db: Session, project_id: UUID, current_user_id: UUID, filters: RequirementFilters, *, prefetch: bool = True,
) -> FilteredRequirements:
    """`filter_requirement_rows` with the full `Requirement` records loaded for every kept row, and (by default)
    their `ListPrefetch`: for a caller that works on all matching records (the record table export).

    Args:
        db / project_id / current_user_id / filters: As for `filter_requirement_rows`; rows come in the project's
            component, category and manual order.
        prefetch: Load the per-row lookups for the kept rows (default); `False` returns an empty prefetch.

    Returns:
        The records, their prefetched lookups (unless skipped) and the unfiltered count.
    """
    found = filter_requirement_rows(db, project_id, current_user_id, filters)
    requirements = requirements_by_ids(db, [row.id for row in found.rows])
    return FilteredRequirements(
        requirements=requirements,
        prefetch=prefetch_for_list(db, [r.id for r in requirements], current_user_id) if prefetch else ListPrefetch(),
        unfiltered=found.unfiltered,
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
    additional_places: Sequence[PlacementPair] | None = None,
    type_id: UUID | None = None,
    type_explicitly_set: bool = False,
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
        additional_places: Make the requirement sit in exactly these further places, each with its own alias
            code (`services.requirement_aliases.set_aliases`), or `None` to leave them.
        type_id / type_explicitly_set: The type chosen from the project's list; `None` with the flag clears it, and
            without the flag the type is left as it is.

    Returns:
        The new version.

    Raises:
        HTTPException: 409 when the requirement is approved (changes then go through a change request) or the status
            move is not legal in the project's lifecycle; 400/422 for a custom field value, person, component or
            category that is not valid for the project, or a review date later than the review policy allows.
    """
    from app.services import requirement_aliases  # imported here: that module builds on this one

    current_version = get_current_version_for_update(db, requirement.id)
    if is_locked(current_version):
        raise HTTPException(status.HTTP_409_CONFLICT, "This requirement is approved; changes must be made via a change request.")
    if status_value is not None:
        check_status_move(db, project.id, requirement.id, current_version.status, status_value)
    if type_explicitly_set and type_id is not None and type_id == current_version.project_type_id:
        # The type already held (an unrelated edit sends it back): kept as it is, even if the project has since
        # disabled or hidden it, so only choosing a different type is checked against the project's list.
        type_explicitly_set = False
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
        project_type_id=resolve_type_or_422(db, project, type_id) if type_explicitly_set else None,
        project_type_explicitly_set=type_explicitly_set,
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
        # An alias in the pair the requirement just moved to would name the same place twice.
        requirement_aliases.drop_redundant(db, project, requirement, actor.id)
    if additional_places is not None:
        requirement_aliases.set_aliases(db, project=project, requirement=requirement, actor_id=actor.id, pairs=additional_places)
    if keywords is not None:
        set_keywords(db, requirement, keywords, actor.id)
    return new_version
