"""
Module: services.reviews

Requirement review scheduling (C-R-06..10): the due/overdue definition shared by the review-status pages and the daily
reminder sweep, and the requirement's `ReviewAdapter` that registers it with the review engine.

Responsibilities:
- `_due_versions_query` and the due lists (`get_due_reviews_for_project`, `get_due_reviews_for_user`): current versions
  whose review date has passed and that no later review has cleared. The lists compare with the caller's calendar day.
- `REQUIREMENT_REVIEW_ADAPTER` (`CORE_REVIEW_ADAPTERS`): the requirement's due list, the reminders still to send and how
  one is recorded, for `services.review_engine`.
- `send_due_review_reminders`: the daily sweep entry point, which hands the work to the engine.

Design decisions:
- A requirement's schedule is a review row: a review recorded on or after the due date clears it, and recording one does not
  move `review_date` (`schedule="review_record"`).
- A due date is a calendar date and a review is an instant, so a review clears a due date once it falls on or after the
  moment that date begins anywhere on Earth (`_EARLIEST_DAY_START`, UTC+14). A person at UTC+10 who reviews on the due date
  morning therefore clears it, where comparing with UTC midnight left it overdue until the afternoon.
- A reminder is stamped on the version (`review_reminder_sent_at`), so each version is reminded once.

Dependencies: `models.requirement`, `services.review_engine` (the sweep), `services.client_date` (the caller's day).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime, timedelta
from uuid import UUID

from sqlalchemy import DateTime, and_, cast, exists, func, or_, select, update
from sqlalchemy.orm import Session

from app.models.enums import PrincipalType
from app.models.notification import NotificationType
from app.models.organization import Organization
from app.models.project import Project
from app.models.requirement import Requirement, RequirementReview, RequirementVersion
from app.modules.seams import DueReview, ReviewAdapter, ReviewReminder
from app.schemas.principal import PrincipalOut
from app.services import review_engine
from app.services.client_date import effective_today
from app.services.codes import qualify
from app.services.principals import (
    principal_filter_clause,
    principal_labels,
    principal_ref,
)
from app.services.rbac import project_group_ids_for_user

# A calendar date begins earliest at UTC+14, 14 hours before UTC midnight of that date.
_EARLIEST_DAY_START = timedelta(hours=14)


def _due_versions_query(project_id: UUID | None = None, as_of: date | None = None):
    """Builds the base query for current requirement versions that are due
    or overdue for review (C-R-09): `review_date` is set, has passed, and no
    `RequirementReview` has been recorded since that date.

    Args:
        project_id: Limits the query to one project, or `None` for every project.
        as_of: The calendar day the review date is compared with; defaults to the caller's day (`effective_today()`).
    """
    already_reviewed = exists().where(
        and_(
            RequirementReview.requirement_id == Requirement.id,
            RequirementReview.reviewed_at
            >= func.timezone("UTC", cast(RequirementVersion.review_date, DateTime) - _EARLIEST_DAY_START),
        )
    )
    query = (
        select(RequirementVersion, Requirement)
        .join(Requirement, Requirement.id == RequirementVersion.requirement_id)
        .where(
            RequirementVersion.valid_to.is_(None),
            RequirementVersion.review_date.is_not(None),
            RequirementVersion.review_date <= (as_of or effective_today()),
            Requirement.is_archived.is_(False),
            ~already_reviewed,
        )
    )
    if project_id is not None:
        query = query.where(Requirement.project_id == project_id)
    return query


def get_due_reviews_for_project(db: Session, project_id: UUID) -> list[tuple[RequirementVersion, Requirement]]:
    """Returns (version, requirement) pairs due/overdue for review in a project (C-R-09)."""
    return [(version, requirement) for version, requirement in db.execute(_due_versions_query(project_id=project_id)).all()]


def reviewer_labels(
    db: Session, versions: list[RequirementVersion]
) -> dict[tuple[str, UUID], PrincipalOut]:
    """Display data for the reviewer of every version in `versions`, in one batch."""
    return principal_labels(db, [principal_ref(v.reviewer_type, v.reviewer_id) for v in versions])


def get_due_reviews_for_user(db: Session, user_id: UUID) -> list[tuple[RequirementVersion, Requirement]]:
    """Returns (version, requirement) pairs assigned to `user_id` as reviewer,
    due/overdue, across every project (C-R-09/C-R-10). A review assigned to a
    group the user belongs to counts as theirs: any one member may record it.

    Unlike `get_due_reviews_for_project`, this spans every project the caller has a role on, so its router
    (`routers/reviews.py`) has no single id to gate behind `require_project_view`/`require_org_role` (whose
    `_require_org_active` check would otherwise apply). The query therefore joins `Project`/`Organization` and
    filters on `is_active`, so a requirement in a disabled organisation never appears in a due list.
    """
    project_group_ids = _project_group_ids_with_due_reviews(db, user_id)
    mine = principal_filter_clause(db, user_id, RequirementVersion.reviewer_type, RequirementVersion.reviewer_id)
    if project_group_ids:
        mine = or_(
            mine,
            and_(
                RequirementVersion.reviewer_type == PrincipalType.PROJECT_GROUP.value,
                RequirementVersion.reviewer_id.in_(project_group_ids),
            ),
        )
    query = (
        _due_versions_query()
        .where(mine)
        .join(Project, Project.id == Requirement.project_id)
        .join(Organization, Organization.id == Project.organization_id)
        .where(Organization.is_active.is_(True))
    )
    return [(version, requirement) for version, requirement in db.execute(query).all()]


def _project_group_ids_with_due_reviews(db: Session, user_id: UUID) -> set[UUID]:
    """The project groups the user belongs to that are named as reviewer on a due review. Project groups
    are per project, so membership is resolved only for the projects that have such a review."""
    project_ids = db.scalars(
        select(Requirement.project_id)
        .join(RequirementVersion, RequirementVersion.requirement_id == Requirement.id)
        .where(
            RequirementVersion.valid_to.is_(None),
            RequirementVersion.review_date.is_not(None),
            RequirementVersion.review_date <= effective_today(),
            RequirementVersion.reviewer_type == PrincipalType.PROJECT_GROUP.value,
            Requirement.is_archived.is_(False),
        )
        .distinct()
    ).all()
    found: set[UUID] = set()
    for project_id in project_ids:
        found |= project_group_ids_for_user(db, user_id, project_id)
    return found


def _adapter_due_reviews(db: Session, project_id: UUID, as_of: date) -> Sequence[DueReview]:
    """`ReviewAdapter.due_reviews` for requirements: the project's due versions, oldest due date first."""
    rows = sorted(
        ((version, requirement) for version, requirement in db.execute(_due_versions_query(project_id, as_of)).all()),
        key=lambda pair: (pair[0].review_date, pair[1].unique_code),
    )
    return [
        DueReview(artefact_id=requirement.id, due_on=version.review_date, owner=principal_ref(version.reviewer_type, version.reviewer_id))
        for version, requirement in rows
        if version.review_date is not None
    ]


def _pending_reminders(db: Session) -> Sequence[ReviewReminder]:
    """`ReviewAdapter.pending_reminders` for requirements: every current, unarchived version with a review date whose
    reminder has not been sent."""
    rows = db.execute(
        select(RequirementVersion, Requirement, Project)
        .join(Requirement, Requirement.id == RequirementVersion.requirement_id)
        .join(Project, Project.id == Requirement.project_id)
        .where(
            RequirementVersion.valid_to.is_(None),
            RequirementVersion.review_date.is_not(None),
            RequirementVersion.review_reminder_sent_at.is_(None),
            Requirement.is_archived.is_(False),
        )
    ).all()
    return [
        ReviewReminder(
            artefact_id=requirement.id, project_id=project.id, due_on=version.review_date, title=version.name,
            code=qualify(project.code, requirement.unique_code),
            owner=principal_ref(version.reviewer_type, version.reviewer_id), lead_days=version.review_lead_days,
        )
        for version, requirement, project in rows
        if version.review_date is not None
    ]


def _mark_reminded(db: Session, requirement_ids: Sequence[UUID], when: datetime) -> None:
    """`ReviewAdapter.mark_reminded` for requirements: stamps each one's current version."""
    db.execute(
        update(RequirementVersion)
        .where(RequirementVersion.requirement_id.in_(requirement_ids), RequirementVersion.valid_to.is_(None))
        .values(review_reminder_sent_at=when)
    )
    db.flush()


REQUIREMENT_REVIEW_ADAPTER = ReviewAdapter(
    schedule="review_record", due_reviews=_adapter_due_reviews, pending_reminders=_pending_reminders,
    mark_reminded=_mark_reminded, notification_type=NotificationType.REQUIREMENT_REVIEW_DUE.value,
)

CORE_REVIEW_ADAPTERS: dict[str, ReviewAdapter] = {"requirement": REQUIREMENT_REVIEW_ADAPTER}
"""The review adapters of the core record types, registered with `modules.registry.get_review_adapters` (module key `""`)."""


def send_due_review_reminders(db: Session) -> None:
    """Daily sweep (C-R-08): sends every review reminder that is due, for requirements and for any other type whose adapter
    hands over its reminders (`services.review_engine.send_review_reminders`)."""
    review_engine.send_review_reminders(db)
