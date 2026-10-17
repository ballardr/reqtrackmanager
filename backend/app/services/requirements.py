"""
Module: services.requirements

Core requirement business logic: unique ID generation (C-G-06, C-G-07),
versioned content changes (C-A-02), the change-request-only edit lock once a
requirement is approved (C-G-12), archival (C-A-06), and keyword/traceability
management (C-M-01, C-G-09).
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import PrincipalType, RequirementLevel, RequirementStatus
from app.models.organization import Organization
from app.models.project import Project, ProjectCategory, ProjectComponent
from app.models.requirement import Requirement, RequirementKeyword, RequirementVersion
from app.models.user import User
from app.modules.registry import ArtefactChange
from app.schemas.principal import PrincipalOut, PrincipalRef
from app.services.artefact_changes import notify_artefact_changed, requirement_content_changed
from app.services.principals import principal_columns, principal_labels, principal_ref
from app.services.rbac import lock_project_for_update

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

    for kw in dict.fromkeys(k.strip().lower() for k in keywords if k.strip()):
        db.add(RequirementKeyword(requirement_id=requirement.id, keyword=kw))

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


def set_keywords(db: Session, requirement: Requirement, keywords: list[str]) -> None:
    """Replaces a requirement's keyword set (C-M-01)."""
    db.execute(RequirementKeyword.__table__.delete().where(RequirementKeyword.requirement_id == requirement.id))
    for kw in dict.fromkeys(k.strip().lower() for k in keywords if k.strip()):
        db.add(RequirementKeyword(requirement_id=requirement.id, keyword=kw))


def get_keywords(db: Session, requirement_id: UUID) -> list[str]:
    return list(db.scalars(select(RequirementKeyword.keyword).where(RequirementKeyword.requirement_id == requirement_id)).all())
