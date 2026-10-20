"""
Module: services.reviews

Requirement review scheduling business logic (Massif v3, C-R-06..10): the
due/overdue definition shared by the review-status pages and the daily
reminder sweep, and the sweep itself.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from sqlalchemy import and_, exists, or_, select
from sqlalchemy.orm import Session

from app.models.enums import PrincipalType
from app.models.notification import NotificationType
from app.models.organization import Organization
from app.models.project import Project
from app.models.requirement import Requirement, RequirementReview, RequirementVersion
from app.models.user import User
from app.schemas.principal import PrincipalOut
from app.services import notifications
from app.services.codes import qualify
from app.services.principals import (
    principal_filter_clause,
    principal_labels,
    principal_recipients,
    principal_ref,
)
from app.services.rbac import get_effective_project_managers, project_group_ids_for_user


def _due_versions_query(project_id: UUID | None = None):
    """Builds the base query for current requirement versions that are due
    or overdue for review (C-R-09): `review_date` is set, has passed, and no
    `RequirementReview` has been recorded since that date.
    """
    already_reviewed = exists().where(
        and_(
            RequirementReview.requirement_id == Requirement.id,
            RequirementReview.reviewed_at >= RequirementVersion.review_date,
        )
    )
    query = (
        select(RequirementVersion, Requirement)
        .join(Requirement, Requirement.id == RequirementVersion.requirement_id)
        .where(
            RequirementVersion.valid_to.is_(None),
            RequirementVersion.review_date.is_not(None),
            RequirementVersion.review_date <= date.today(),
            Requirement.is_archived.is_(False),
            ~already_reviewed,
        )
    )
    if project_id is not None:
        query = query.where(Requirement.project_id == project_id)
    return query


def get_due_reviews_for_project(db: Session, project_id: UUID) -> list[tuple[RequirementVersion, Requirement]]:
    """Returns (version, requirement) pairs due/overdue for review in a project (C-R-09)."""
    return list(db.execute(_due_versions_query(project_id=project_id)).all())


def reviewer_labels(
    db: Session, versions: list[RequirementVersion]
) -> dict[tuple[str, UUID], PrincipalOut]:
    """Display data for the reviewer of every version in `versions`, in one batch."""
    return principal_labels(db, [principal_ref(v.reviewer_type, v.reviewer_id) for v in versions])


def get_due_reviews_for_user(db: Session, user_id: UUID) -> list[tuple[RequirementVersion, Requirement]]:
    """Returns (version, requirement) pairs assigned to `user_id` as reviewer,
    due/overdue, across every project (C-R-09/C-R-10). A review assigned to a
    group the user belongs to counts as theirs: any one member may record it.

    Unlike `get_due_reviews_for_project`, this spans every project the
    caller has any role on rather than one specific `project_id`, so its
    router (`routers/reviews.py`) has no single id to gate behind
    `require_project_view`/`require_org_role` (whose `_require_org_active`
    check would otherwise cover this for free) — a hardening-review finding:
    this query joined straight from `Requirement` to `RequirementVersion`
    with no `Project`/`Organization` involved at all, so a requirement in a
    since-disabled organisation kept appearing in a reviewer's due list
    indefinitely, the one org/project-scoped read in the app that wasn't
    wired to the disable gate. Joining `Project`/`Organization` here and
    filtering on `is_active` closes that gap directly, since there's no
    dependency factory to lean on.
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
    return list(db.execute(query).all())


def _project_group_ids_with_due_reviews(db: Session, user_id: UUID) -> set[UUID]:
    """The project groups the user belongs to that are named as reviewer on a due review. Project groups
    are per project, so membership is resolved only for the projects that have such a review."""
    project_ids = db.scalars(
        select(Requirement.project_id)
        .join(RequirementVersion, RequirementVersion.requirement_id == Requirement.id)
        .where(
            RequirementVersion.valid_to.is_(None),
            RequirementVersion.review_date.is_not(None),
            RequirementVersion.review_date <= date.today(),
            RequirementVersion.reviewer_type == PrincipalType.PROJECT_GROUP.value,
            Requirement.is_archived.is_(False),
        )
        .distinct()
    ).all()
    found: set[UUID] = set()
    for project_id in project_ids:
        found |= project_group_ids_for_user(db, user_id, project_id)
    return found


def send_due_review_reminders(db: Session) -> None:
    """Daily sweep (C-R-08): for every current requirement version whose
    review reminder is due (today >= review_date - lead_days) and hasn't
    already been sent, notifies the assigned reviewer (every member of a reviewer
    group; or every project manager if none can be notified) and stamps `review_reminder_sent_at`.
    """
    today = date.today()
    candidates = db.execute(
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

    for version, requirement, project in candidates:
        lead_days = version.review_lead_days if version.review_lead_days is not None else project.review_reminder_lead_days_default
        if today < version.review_date - timedelta(days=lead_days):
            continue

        # Every active member of a reviewer group; the project managers when there is no reviewer or the
        # group has nobody to notify.
        recipient_ids: set[UUID] = principal_recipients(db, [principal_ref(version.reviewer_type, version.reviewer_id)])
        if not recipient_ids:
            recipient_ids = get_effective_project_managers(db, project.id)
        for recipient_id in recipient_ids:
            recipient = db.get(User, recipient_id)
            if recipient is None:
                continue
            notifications.notify(
                db, recipient, notification_type=NotificationType.REQUIREMENT_REVIEW_DUE,
                title=f"Review due: {version.name}",
                body=f"{qualify(project.code, requirement.unique_code)} is due for review by {version.review_date.isoformat()}.",
                project_id=project.id, entity_type="requirement", entity_id=str(requirement.id),
            )
        version.review_reminder_sent_at = datetime.now(UTC)

    db.commit()
