"""
Module: modules.traceability.exception_governance

How a traceability exception takes part in the governance engine: its status path, its review schedule and the progress
it reports to governance health.

Responsibilities:
- `LIFECYCLES`: the path from requested to approved, built from `exceptions.TRANSITIONS`.
- `REVIEW_ADAPTERS`: the review date of a live exception, reminded by the core review engine.
- `HEALTH_PROVIDERS`: how many live exceptions are in force.

Design decisions:
- Approved is gated, and of the people who submitted a record only an organisation administrator may approve it
  (`self_approval_org_admins_only`).
- No step is optional and none can be skipped: every state records a decision.
- A review is scheduled only while the exception is awaiting a decision or in force; an expired one has nothing to review.
- A reminder goes to the requester (every member of a requester group), else the review policy's default owner, else the
  project managers, as for any type.
- Health counts requested and approved exceptions; those approved and not expired are the settled ones, so exceptions
  waiting for a decision or lapsed stand out from those covering a record.

Dependencies: `exceptions`, `models`, `modules.registry`, `modules.seams`, `services.lifecycles`.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, date, datetime

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.project import Project
from app.models.user import User
from app.modules.registry import LifecycleDefinition
from app.modules.seams import DueReview, HealthMeasure, HealthProvider, ReminderMark, ReviewAdapter, ReviewReminder
from app.modules.traceability import exceptions
from app.modules.traceability._shared import EXCEPTION_ARTEFACT_TYPE, TRACEABILITY_EXCEPTIONS
from app.modules.traceability.enums import ExceptionStatus
from app.modules.traceability.labels import EXCEPTION_STATUS_LABEL
from app.modules.traceability.models import TraceabilityException
from app.services.codes import qualify
from app.services.lifecycles import table_from_enum
from app.services.principals import principal_ref

_LIVE = (ExceptionStatus.REQUESTED, ExceptionStatus.APPROVED)


def _entry_guard(db: Session, user: User, project: Project, record_id: uuid.UUID, state: str) -> None:
    """The check the approval makes, for the lifecycle engine: raises 403 for anyone who may not approve."""
    exception = db.get(TraceabilityException, record_id)
    if exception is None or state != ExceptionStatus.APPROVED.value:
        return
    entry = None if exception.rule_id is None else exceptions.rule_entries(db, project).get(exception.rule_id)
    exceptions.require_may_move(db, project, exception, entry, ExceptionStatus.APPROVED, user)


LIFECYCLES: dict[str, LifecycleDefinition] = {
    EXCEPTION_ARTEFACT_TYPE: LifecycleDefinition(
        label="Traceability exception",
        path=(ExceptionStatus.REQUESTED.value, ExceptionStatus.APPROVED.value),
        transitions=table_from_enum(exceptions.TRANSITIONS), labels=EXCEPTION_STATUS_LABEL,
        gated=(ExceptionStatus.APPROVED.value,), entry_guard=_entry_guard, record_model=TraceabilityException,
        self_approval_org_admins_only=True,
    ),
}


# --- reviews ----------------------------------------------------------------------------------------


def _live_conditions(today: date) -> tuple:
    return (
        TraceabilityException.review_date.is_not(None), TraceabilityException.is_archived.is_(False),
        TraceabilityException.status.in_(_LIVE),
        or_(TraceabilityException.expires_on.is_(None), TraceabilityException.expires_on >= today),
    )


def _due_reviews(db: Session, project_id: uuid.UUID, as_of: date) -> Sequence[DueReview]:
    """`ReviewAdapter.due_reviews`: live exceptions whose review date is on or before `as_of`, oldest first."""
    rows = db.scalars(
        select(TraceabilityException).where(
            TraceabilityException.project_id == project_id, TraceabilityException.review_date <= as_of,
            *_live_conditions(as_of),
        ).order_by(TraceabilityException.review_date, TraceabilityException.unique_code)
    )
    return [
        DueReview(artefact_id=r.id, due_on=r.review_date, owner=principal_ref(r.requester_type, r.requester_id))
        for r in rows if r.review_date is not None
    ]


def _pending_reminders(db: Session) -> Sequence[ReviewReminder]:
    """`ReviewAdapter.pending_reminders`: every live exception not yet told both "due" and "overdue" for its date."""
    rows = db.execute(
        select(TraceabilityException, Project).join(Project, Project.id == TraceabilityException.project_id).where(
            *_live_conditions(datetime.now(UTC).date()),
            or_(
                TraceabilityException.review_due_notified_for.is_distinct_from(TraceabilityException.review_date),
                TraceabilityException.review_overdue_notified_for.is_distinct_from(TraceabilityException.review_date),
            ),
        )
    ).all()
    return [
        ReviewReminder(
            artefact_id=row.id, project_id=project.id, due_on=row.review_date, title=row.title,
            code=qualify(project.code, row.unique_code), owner=principal_ref(row.requester_type, row.requester_id),
            reminded_for=row.review_due_notified_for, overdue_reminded_for=row.review_overdue_notified_for,
        )
        for row, project in rows
        if row.review_date is not None
    ]


def _mark_reminded(db: Session, marks: Sequence[ReminderMark], when: datetime) -> None:
    """`ReviewAdapter.mark_reminded`: stamps the date each reminder was sent for, so a new date re-arms it."""
    by_id = {m.artefact_id: m for m in marks}
    for row in db.scalars(select(TraceabilityException).where(TraceabilityException.id.in_(list(by_id)))):
        mark = by_id[row.id]
        if mark.overdue:
            row.review_overdue_notified_for = mark.due_on
        else:
            row.review_due_notified_for = mark.due_on
    db.flush()


def _message(reminder: ReviewReminder, overdue: bool) -> tuple[str, str]:
    if overdue:
        return (
            f"{reminder.code}: exception review overdue",
            f'The review of "{reminder.title}" was due on {reminder.due_on.isoformat()}.',
        )
    return (
        f"{reminder.code}: exception review due soon",
        f'The review of "{reminder.title}" is due on {reminder.due_on.isoformat()}.',
    )


REVIEW_ADAPTERS: dict[str, ReviewAdapter] = {
    EXCEPTION_ARTEFACT_TYPE: ReviewAdapter(
        schedule="next_review_date", due_reviews=_due_reviews, pending_reminders=_pending_reminders,
        mark_reminded=_mark_reminded, notification_type=exceptions.REVIEW_DUE_TYPE,
        overdue_notification_type=exceptions.REVIEW_OVERDUE_TYPE, message=_message, sub_component=TRACEABILITY_EXCEPTIONS,
    ),
}


# --- health -----------------------------------------------------------------------------------------


def measure_exceptions(db: Session, project_id: uuid.UUID) -> HealthMeasure:
    """The project's live requested and approved exceptions, of which those approved and not expired are in force."""
    today = datetime.now(UTC).date()
    in_force = (
        (TraceabilityException.status == ExceptionStatus.APPROVED)
        & or_(TraceabilityException.expires_on.is_(None), TraceabilityException.expires_on >= today)
    )
    total, done = db.execute(
        select(func.count(), func.count().filter(in_force)).where(
            TraceabilityException.project_id == project_id, TraceabilityException.is_archived.is_(False),
            TraceabilityException.status.in_(_LIVE),
        )
    ).one()
    return HealthMeasure(total=total, done=done)


HEALTH_PROVIDERS: tuple[HealthProvider, ...] = (
    HealthProvider(
        key="traceability_exceptions", label="Traceability exceptions", artefact_type=EXCEPTION_ARTEFACT_TYPE,
        kind="completion", measure=measure_exceptions, sub_component=TRACEABILITY_EXCEPTIONS,
    ),
)
