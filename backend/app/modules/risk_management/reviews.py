"""
Module: modules.risk_management.reviews

Periodic risk reviews: `record_review` stores one review with a snapshot of the
ratings (derived on read, so they would otherwise change with the matrix) and
moves `review_date`; `list_reviews` returns the history; `count_stale_treatments`
counts verdicts awaiting reassessment, which block confirming a risk.
A review is immutable (a mistake is corrected by a newer one) and records a
judgement without editing the risk; `next_review_date` is required (nullable).

`RISK_REVIEW_ADAPTER` registers the risk's schedule with the core review engine
(`services.review_engine`): the due list, the reminders still to send (one "due" and
one "overdue" per `review_date`, stamped on the risk) and who hears of them. The
engine applies the project's review policy: its reminder lead, its default owner
and its interval, which caps the next review date `record_review` accepts.

Dependencies: `services.review_engine` (policy), `services.client_date` (the caller's day).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, date, datetime

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.project import Project
from app.models.user import User
from app.modules.risk_management.alerts import REVIEW_DUE_TYPE, REVIEW_OVERDUE_TYPE, manager_recipients
from app.modules.risk_management.enums import RiskReviewOutcome, RiskStatus, TreatmentAssessmentStatus
from app.modules.risk_management.labels import RISK_REVIEW_OUTCOME_LABEL
from app.modules.risk_management.models import Risk, RiskReview, RiskTreatmentAssessment, RiskVersion
from app.modules.risk_management.ratings import RatingContext, rate_version
from app.modules.risk_management.service import (
    RISK_ARTEFACT_TYPE,
    RISK_SUBCOMPONENT_KEY,
    apply_new_version,
)
from app.modules.risk_management.treatment import effective_treatment_counts
from app.modules.seams import DueReview, ReminderMark, ReviewAdapter, ReviewReminder
from app.services import review_engine
from app.services.client_date import effective_today
from app.services.codes import qualify
from app.services.principals import principal_ref


def count_stale_treatments(db: Session, risk_id: uuid.UUID) -> int:
    """How many of the risk's treatment verdicts are `NEEDS_REASSESSMENT`."""
    return db.scalar(
        select(func.count()).select_from(RiskTreatmentAssessment).where(
            RiskTreatmentAssessment.risk_id == risk_id,
            RiskTreatmentAssessment.status == TreatmentAssessmentStatus.NEEDS_REASSESSMENT,
        )
    ) or 0


def record_review(
    db: Session, risk: Risk, current: RiskVersion, actor: User, ctx: RatingContext,
    *, outcome: RiskReviewOutcome, notes: str, next_review_date: date | None,
) -> RiskReview:
    """Records a review of `risk` and sets the date of the next one.

    The caller has locked the risk row, re-read `current` under that lock and
    authorised the actor. Does not commit or audit-log.

    Args:
        current: The risk's current version.
        ctx: The project's rating context (for the snapshot).
        outcome: What the review concluded.
        notes: The reviewer's findings; must not be blank.
        next_review_date: When the next review is due, or `None` for none. Must
            be in the future (the caller's day) and, when the project's review policy
            sets an interval, no later than that many days from today.

    Returns:
        The stored review.

    Raises:
        ValueError: If the risk is archived or `CLOSED`, `notes` is blank,
            `next_review_date` is not in the future or breaks the policy's interval,
            or `outcome` is `CONFIRMED` while a treatment verdict needs reassessment.
    """
    if risk.is_archived:
        raise ValueError("An archived risk cannot be reviewed; unarchive it first.")
    if current.status == RiskStatus.CLOSED:
        raise ValueError("A closed risk is no longer reviewed; reopen it first.")
    notes = notes.strip()
    if not notes:
        raise ValueError("A review needs notes recording what was found.")
    now = datetime.now(UTC)
    today = effective_today()
    if next_review_date is not None and next_review_date <= today:
        raise ValueError("The next review date must be in the future.")
    review_engine.check_next_review_date(review_engine.review_policy(db, risk.project_id, RISK_ARTEFACT_TYPE), today, next_review_date)
    stale = count_stale_treatments(db, risk.id)
    if outcome == RiskReviewOutcome.CONFIRMED and stale:
        raise ValueError(
            f"{stale} treatment{'s need' if stale != 1 else ' needs'} reassessment; reassess "
            f"{'them' if stale != 1 else 'it'} first, or record the review as reassessed."
        )

    inherent, residual = rate_version(ctx, current)
    review = RiskReview(
        risk_id=risk.id, risk_version_number=current.version_number, reviewed_by=actor.id, reviewed_at=now,
        outcome=outcome, notes=notes, risk_status=current.status,
        inherent_rating_label=inherent.label if inherent else None,
        inherent_rating_score=inherent.normalised if inherent else None,
        residual_rating_label=residual.label if residual else None,
        residual_rating_score=residual.normalised if residual else None,
        effective_treatment_count=effective_treatment_counts(db, [risk.id]).get(risk.id, 0),
        scheduled_for=current.review_date, next_review_date=next_review_date,
    )
    db.add(review)
    if next_review_date != current.review_date:
        outcome_label = RISK_REVIEW_OUTCOME_LABEL.get(outcome.value, outcome.value)
        next_date = next_review_date.isoformat() if next_review_date else "none"
        apply_new_version(
            db, risk, current, actor, changes={"review_date": next_review_date},
            change_note=f"Reviewed ({outcome_label}); next review {next_date}.",
        )
    db.flush()
    return review


def list_reviews(db: Session, risk_id: uuid.UUID) -> list[RiskReview]:
    """A risk's reviews, newest first."""
    return list(db.scalars(
        select(RiskReview).where(RiskReview.risk_id == risk_id).order_by(RiskReview.reviewed_at.desc(), RiskReview.id)
    ).all())


def _due_reviews(db: Session, project_id: uuid.UUID, as_of: date) -> Sequence[DueReview]:
    """`ReviewAdapter.due_reviews` for risks: the project's open risks whose review date is on or before `as_of`, oldest
    date first."""
    rows = db.execute(
        select(Risk, RiskVersion).join(RiskVersion, RiskVersion.risk_id == Risk.id).where(
            Risk.project_id == project_id, RiskVersion.valid_to.is_(None), RiskVersion.review_date.is_not(None),
            RiskVersion.review_date <= as_of, Risk.is_archived.is_(False), RiskVersion.status != RiskStatus.CLOSED,
        ).order_by(RiskVersion.review_date, Risk.unique_code)
    ).all()
    return [
        DueReview(artefact_id=risk.id, due_on=version.review_date, owner=principal_ref(version.owner_type, version.owner_id))
        for risk, version in rows
        if version.review_date is not None
    ]


def _pending_reminders(db: Session) -> Sequence[ReviewReminder]:
    """`ReviewAdapter.pending_reminders` for risks: every open risk with a review date that has not been told both of
    "due" and "overdue" for that date."""
    rows = db.execute(
        select(Risk, RiskVersion, Project)
        .join(RiskVersion, RiskVersion.risk_id == Risk.id).join(Project, Project.id == Risk.project_id)
        .where(
            RiskVersion.valid_to.is_(None), RiskVersion.review_date.is_not(None), Risk.is_archived.is_(False),
            RiskVersion.status != RiskStatus.CLOSED,
            or_(
                Risk.review_due_notified_for.is_distinct_from(RiskVersion.review_date),
                Risk.review_overdue_notified_for.is_distinct_from(RiskVersion.review_date),
            ),
        )
    ).all()
    return [
        ReviewReminder(
            artefact_id=risk.id, project_id=project.id, due_on=version.review_date, title=version.title,
            code=qualify(project.code, risk.unique_code), owner=principal_ref(version.owner_type, version.owner_id),
            reminded_for=risk.review_due_notified_for, overdue_reminded_for=risk.review_overdue_notified_for,
        )
        for risk, version, project in rows
        if version.review_date is not None
    ]


def _mark_reminded(db: Session, marks: Sequence[ReminderMark], when: datetime) -> None:
    """`ReviewAdapter.mark_reminded` for risks: stamps the due date each reminder was sent for on the risk, so the next
    reschedule re-arms it."""
    by_id = {m.artefact_id: m for m in marks}
    for risk in db.scalars(select(Risk).where(Risk.id.in_(list(by_id)))):
        mark = by_id[risk.id]
        if mark.overdue:
            risk.review_overdue_notified_for = mark.due_on
        else:
            risk.review_due_notified_for = mark.due_on
    db.flush()


def _message(reminder: ReviewReminder, overdue: bool) -> tuple[str, str]:
    """`ReviewAdapter.message` for risks: the title names the risk's code, the body its title and date."""
    if overdue:
        return (f"{reminder.code}: review overdue", f'The review of "{reminder.title}" was due on {reminder.due_on.isoformat()}.')
    return (f"{reminder.code}: review due soon", f'The review of "{reminder.title}" is due on {reminder.due_on.isoformat()}.')


def _fallback_recipients(db: Session, reminder: ReviewReminder) -> set[uuid.UUID]:
    """`ReviewAdapter.fallback_recipients` for risks: the project's Risk Managers and project managers."""
    return manager_recipients(db, reminder.project_id) if reminder.project_id is not None else set()


RISK_REVIEW_ADAPTER = ReviewAdapter(
    schedule="next_review_date", due_reviews=_due_reviews, pending_reminders=_pending_reminders,
    mark_reminded=_mark_reminded, notification_type=REVIEW_DUE_TYPE, overdue_notification_type=REVIEW_OVERDUE_TYPE,
    message=_message, fallback_recipients=_fallback_recipients, sub_component=RISK_SUBCOMPONENT_KEY,
)
