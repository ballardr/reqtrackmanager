"""
Module: modules.risk_management.reviews

Periodic risk reviews (overview §11.6).

Responsibilities:
- `record_review`: validate and store one review, snapshot the ratings it was
  made against, and move the risk's `review_date` to the date the review sets.
- `list_reviews`: a risk's review history, newest first.
- `count_stale_treatments`: how many treatment verdicts are waiting for
  reassessment (a review cannot confirm a risk while any are).

Design decisions:
- A review is an immutable record; a mistake is corrected by a newer review.
  Nothing is updated or deleted, so the history can be relied on.
- A review records a judgement, it does not edit the risk. Changes the reviewer
  makes (a new rating, a status move) are ordinary versions made through the
  normal endpoints, which keeps every edit going through its own authorisation
  and guards; `outcome` says whether the review led to any.
- The rating snapshot is stored because ratings are derived on read and move
  whenever the matrix is edited; without it the history would silently rewrite
  itself. Decided by: Agent.
- `next_review_date` is required (nullable): a review that leaves the old date in
  place would make the risk overdue forever, so the reviewer states the next date
  or explicitly says there is none. Decided by: Agent.
- A review cannot *confirm* a risk while a treatment verdict is waiting for
  reassessment: "the assessment still stands" would contradict the flag the
  change detection raised. Decided by: Agent.

Dependencies: this module's models, `ratings`, `service.apply_new_version`.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.user import User
from app.modules.risk_management.enums import RiskReviewOutcome, RiskStatus, TreatmentAssessmentStatus
from app.modules.risk_management.labels import RISK_REVIEW_OUTCOME_LABEL
from app.modules.risk_management.models import Risk, RiskReview, RiskTreatmentAssessment, RiskVersion
from app.modules.risk_management.ratings import RatingContext, rate_version
from app.modules.risk_management.service import apply_new_version
from app.modules.risk_management.treatment import effective_treatment_counts


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
            be in the future.

    Returns:
        The stored review.

    Raises:
        ValueError: If the risk is archived or `CLOSED`, `notes` is blank,
            `next_review_date` is not in the future, or `outcome` is `CONFIRMED`
            while a treatment verdict needs reassessment.
    """
    if risk.is_archived:
        raise ValueError("An archived risk cannot be reviewed; unarchive it first.")
    if current.status == RiskStatus.CLOSED:
        raise ValueError("A closed risk is no longer reviewed; reopen it first.")
    notes = notes.strip()
    if not notes:
        raise ValueError("A review needs notes recording what was found.")
    now = datetime.now(UTC)
    if next_review_date is not None and next_review_date <= now.date():
        raise ValueError("The next review date must be in the future.")
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
