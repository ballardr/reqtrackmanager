"""
Module: modules.compliance.review_adapter

How the core review engine (`services.review_engine`) reads Compliance's scheduled reviews: the due list, the reminders
still to send (one "due soon" and one "overdue" notice for each scheduled review, stamped on it) and who hears of them.

Responsibilities:
- `COMPLIANCE_REVIEW_ADAPTER`, registered under the key `compliance_review` in `ModuleDefinition.review_adapters`.
- Cover both owners of a review: a project assignment's review (the project's review policy applies) and a standard's
  review (the organisation owns it, so no project policy applies and the notice opens the standard).

Design decisions:
- The reminder lead is the module's own 14 days (`service.COMPLIANCE_REVIEW_DUE_WARNING_DAYS`), used in place of the
  project's default lead; a review policy's lead still overrides it.
- Recipients are unchanged: the review's owner (every member of a group) together with the project's Compliance Officers
  (a standard's review: the organisation's Compliance Managers). They are the reviewer and the people always told
  (`also_notify`), so a review policy's default owner stands in for a review with no owner and adds to the officers.
- The sweep stamps the same two columns as before, so a review is told once per notification.

Dependencies: `models`, `service` (the recipient lookups), `services.review_engine` (through the registry).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import date, datetime

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.notification import NotificationType
from app.modules.compliance.enums import ComplianceReviewStatus
from app.modules.compliance.models import ComplianceReview, ComplianceStandard, ProjectCompliance
from app.modules.compliance.service import (
    COMPLIANCE_REVIEW_DUE_WARNING_DAYS,
    get_effective_compliance_managers,
    get_effective_compliance_officers,
)
from app.modules.seams import DueReview, ReminderMark, ReviewAdapter, ReviewReminder
from app.services.principals import principal_ref

REVIEW_ARTEFACT_TYPE = "compliance_review"


def _due_reviews(db: Session, project_id: uuid.UUID, as_of: date) -> Sequence[DueReview]:
    """`ReviewAdapter.due_reviews`: the project's scheduled reviews due on or before `as_of`, oldest date first."""
    rows = db.scalars(
        select(ComplianceReview).join(ProjectCompliance, ProjectCompliance.id == ComplianceReview.project_compliance_id)
        .where(
            ProjectCompliance.project_id == project_id, ComplianceReview.status == ComplianceReviewStatus.SCHEDULED,
            ComplianceReview.next_due_date <= as_of,
        ).order_by(ComplianceReview.next_due_date, ComplianceReview.id)
    ).all()
    return [DueReview(r.id, r.next_due_date, principal_ref(r.owner_type, r.owner_id)) for r in rows]


def _reminder(review: ComplianceReview, project_id: uuid.UUID | None, organization_id: uuid.UUID | None, entity: tuple[str, str]) -> ReviewReminder:
    """The reminder of `review`, with what has been told so far read from its two stamps."""
    due = review.next_due_date
    return ReviewReminder(
        artefact_id=review.id, project_id=project_id, organization_id=organization_id, due_on=due,
        title=review.frequency_label, code="", owner=principal_ref(review.owner_type, review.owner_id),
        lead_days=None, entity=entity,
        reminded_for=due if review.due_reminder_sent_at is not None else None,
        overdue_reminded_for=due if review.overdue_notified_at is not None else None,
    )


def _pending_reminders(db: Session) -> Sequence[ReviewReminder]:
    """`ReviewAdapter.pending_reminders`: every scheduled review that has not been told both of "due" and "overdue"."""
    reviews = db.scalars(
        select(ComplianceReview).where(
            ComplianceReview.status == ComplianceReviewStatus.SCHEDULED,
            or_(ComplianceReview.due_reminder_sent_at.is_(None), ComplianceReview.overdue_notified_at.is_(None)),
        )
    ).all()
    assignments = {
        a.id: a for a in db.scalars(select(ProjectCompliance).where(
            ProjectCompliance.id.in_([r.project_compliance_id for r in reviews if r.project_compliance_id is not None])
        ))
    } if reviews else {}
    standards = {
        s.id: s for s in db.scalars(select(ComplianceStandard).where(
            ComplianceStandard.id.in_([r.standard_id for r in reviews if r.standard_id is not None])
        ))
    } if reviews else {}
    out: list[ReviewReminder] = []
    for review in reviews:
        if review.project_compliance_id is not None:
            assignment = assignments.get(review.project_compliance_id)
            if assignment is not None:
                out.append(_reminder(review, assignment.project_id, None, ("compliance_review", str(review.id))))
        elif review.standard_id is not None:
            standard = standards.get(review.standard_id)
            if standard is not None:
                # A standard's review has no project, so the notice names the standard it opens.
                out.append(_reminder(review, None, standard.organization_id, ("compliance_standard", str(standard.id))))
    return out


def _mark_reminded(db: Session, marks: Sequence[ReminderMark], when: datetime) -> None:
    """`ReviewAdapter.mark_reminded`: stamps the "due" or "overdue" column of each review told."""
    by_id = {m.artefact_id: m for m in marks}
    for review in db.scalars(select(ComplianceReview).where(ComplianceReview.id.in_(list(by_id)))):
        if by_id[review.id].overdue:
            review.overdue_notified_at = when
        else:
            review.due_reminder_sent_at = when
    db.flush()


def _message(reminder: ReviewReminder, overdue: bool) -> tuple[str, str]:
    """`ReviewAdapter.message`: the title names the review's frequency, the body its date."""
    if overdue:
        return (
            f"Compliance review overdue: {reminder.title}",
            f"A scheduled compliance review was due on {reminder.due_on.isoformat()}.",
        )
    return (
        f"Compliance review due soon: {reminder.title}",
        f"A scheduled compliance review is due on {reminder.due_on.isoformat()}.",
    )


def _no_fallback(db: Session, reminder: ReviewReminder) -> set[uuid.UUID]:
    """`ReviewAdapter.fallback_recipients`: nobody, because the officers are told whatever the reviewer is."""
    return set()


def _also_notify(db: Session, reminder: ReviewReminder) -> set[uuid.UUID]:
    """`ReviewAdapter.also_notify`: the project's Compliance Officers, or a standard's organisation Compliance Managers."""
    if reminder.project_id is not None:
        return get_effective_compliance_officers(db, reminder.project_id)
    return get_effective_compliance_managers(db, reminder.organization_id) if reminder.organization_id is not None else set()


COMPLIANCE_REVIEW_ADAPTER = ReviewAdapter(
    schedule="next_review_date", due_reviews=_due_reviews, pending_reminders=_pending_reminders,
    mark_reminded=_mark_reminded, notification_type=NotificationType.COMPLIANCE_REVIEW_DUE.value,
    overdue_notification_type=NotificationType.COMPLIANCE_REVIEW_OVERDUE.value, message=_message,
    fallback_recipients=_no_fallback, also_notify=_also_notify, default_lead_days=COMPLIANCE_REVIEW_DUE_WARNING_DAYS,
)
