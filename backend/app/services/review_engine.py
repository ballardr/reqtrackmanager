"""
Module: services.review_engine

The core review engine: how a record type's scheduled review is read, reminded and rescheduled, whatever way the type
stores its schedule. A type registers a `ReviewAdapter` (`modules.registry.get_review_adapters`); this module asks the
adapters, applies the project's review policy and sends the reminders.

Responsibilities:
- `review_policy`: the policy that applies to a type in a project (`GovernanceSeam.REVIEW`), the built-in default when no
  module answers.
- `due_reviews`: every record of a project whose review is due, across the adapters in effect.
- `send_review_reminders`: the one daily sweep over every adapter that hands over its reminders.
- `may_review_as_default_owner`: whether the policy's default owner may record the review of a record that has no reviewer.
- Scheduling rules a type applies when it records a review: `next_due_date` and `check_next_review_date` (the policy's
  interval), `reminder_lead_days` and `reminder_open` (when a reminder is due).

Design decisions:
- The default policy has no interval, lead or owner, so a type behaves exactly as it did before the engine: a project that
  configures nothing, or has Governance off, sees no difference.
- A due date is a calendar date (a person's own day). An interactive caller compares it with
  `client_date.effective_today()`; the sweep has no caller, so it compares with the UTC date, which is at most a day from
  any person's day, and sends each reminder once per due date.
- The reminder goes to the record's own reviewer (every active member of a group), else the policy's default owner, else
  the adapter's fallback (the project managers by default), so a due review never goes unannounced.
- A type with a separate "overdue" notice (`ReviewAdapter.overdue_notification_type`) gets one "due" and one "overdue"
  reminder per due date; a type without one gets a single reminder per due date.
- An interval is the longest gap, never a fixed schedule: a type that stores the next review date stays free to set an
  earlier one.

Dependencies: `modules.registry` and `services.governance_seams` (registrations and policy), `services.principals`
(recipients), `services.notifications`, `services.rbac` (project managers).
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.project import Project
from app.models.user import User
from app.modules import registry
from app.modules.seams import DueReview, GovernanceSeam, ReminderMark, ReviewAdapter, ReviewPolicy, ReviewReminder
from app.services import governance_seams, notifications
from app.services.principals import PrincipalRef, is_principal_member, principal_recipients
from app.services.rbac import get_effective_project_managers

DEFAULT_REMINDER_LEAD_DAYS = 7


def review_policy(db: Session, project_id: uuid.UUID, artefact_type: str) -> ReviewPolicy:
    """The review policy of `artefact_type` in the project.

    Args:
        db: An active database session.
        project_id: The project.
        artefact_type: The registered record type.

    Returns:
        The policy a governance module answers with, else the default policy (no interval, lead or owner).
    """
    policy = governance_seams.resolve_policy(db, project_id, GovernanceSeam.REVIEW, artefact_type)
    return policy if isinstance(policy, ReviewPolicy) else ReviewPolicy()


def next_due_date(policy: ReviewPolicy, reviewed_on: date) -> date | None:
    """The date the next review falls due by the policy's interval.

    Args:
        policy: The type's review policy.
        reviewed_on: The calendar day the review took place.

    Returns:
        `reviewed_on` plus the interval, or `None` when the policy sets no interval.
    """
    if policy.interval_days is None:
        return None
    return reviewed_on + timedelta(days=policy.interval_days)


def check_next_review_date(policy: ReviewPolicy, reviewed_on: date, proposed: date | None) -> None:
    """Refuses a next review date later than the policy's interval allows.

    Args:
        policy: The type's review policy.
        reviewed_on: The calendar day the review took place.
        proposed: The next review date a person chose, or `None` for none.

    Raises:
        ValueError: When the policy sets an interval and `proposed` is missing or later than `reviewed_on` plus the interval.
    """
    latest = next_due_date(policy, reviewed_on)
    if latest is None:
        return
    if proposed is None:
        raise ValueError(f"The review policy needs a next review date no later than {latest.isoformat()}.")
    if proposed > latest:
        raise ValueError(f"The review policy allows the next review no later than {latest.isoformat()}.")


def reminder_lead_days(record_lead: int | None, policy: ReviewPolicy, project_default: int | None) -> int:
    """How many days before the due date the reminder is sent.

    Args:
        record_lead: The record's own lead, or `None`.
        policy: The type's review policy.
        project_default: The project's default lead, or `None`.

    Returns:
        The record's lead, else the policy's, else the project's, else `DEFAULT_REMINDER_LEAD_DAYS`.
    """
    for lead in (record_lead, policy.lead_days, project_default):
        if lead is not None:
            return lead
    return DEFAULT_REMINDER_LEAD_DAYS


def reminder_open(due_on: date, lead_days: int, today: date) -> bool:
    """Whether the reminder for a review due on `due_on` is due: `today` is `lead_days` or fewer days before it, or later."""
    return today >= due_on - timedelta(days=lead_days)


def due_reviews(db: Session, project_id: uuid.UUID, as_of: date) -> list[tuple[str, DueReview]]:
    """The records of a project whose review is due on or before `as_of`.

    Args:
        db: An active database session.
        project_id: The project.
        as_of: The calendar day to compare with (`effective_today()` for a caller).

    Returns:
        `(artefact type, due review)` for each type with an adapter in effect, types in name order and each type's records
        oldest first.
    """
    out: list[tuple[str, DueReview]] = []
    for artefact_type in sorted(registry.get_review_adapters()):
        adapter = governance_seams.review_adapter_for_project(db, project_id, artefact_type)
        if adapter is not None:
            out.extend((artefact_type, due) for due in adapter.due_reviews(db, project_id, as_of))
    return out


def _recipients(
    db: Session, adapter: ReviewAdapter, reminder: ReviewReminder, policy: ReviewPolicy,
    managers: dict[uuid.UUID, set[uuid.UUID]],
) -> set[uuid.UUID]:
    """Who hears about a due review: its own reviewer, else the policy's default owner, else the adapter's fallback, else
    the project managers (read once per project through `managers`; a record with no project has none), plus anyone the
    adapter always adds."""
    recipients = principal_recipients(db, [reminder.owner]) or principal_recipients(db, [policy.default_owner])
    if not recipients:
        if adapter.fallback_recipients is not None:
            recipients = adapter.fallback_recipients(db, reminder)
        elif reminder.project_id is not None:
            if reminder.project_id not in managers:
                managers[reminder.project_id] = get_effective_project_managers(db, reminder.project_id)
            recipients = managers[reminder.project_id]
    if adapter.also_notify is not None:
        recipients = recipients | adapter.also_notify(db, reminder)
    return recipients


def may_review_as_default_owner(
    db: Session, user_id: uuid.UUID, project_id: uuid.UUID, artefact_type: str, record_reviewer: PrincipalRef | None,
) -> bool:
    """Whether the policy's default owner admits `user_id` to record the review of a record.

    The default owner stands in only for a record with no reviewer of its own, so it never narrows or replaces a reviewer a
    record names. It grants the right to record the review and nothing else.

    Args:
        db: An active database session.
        user_id: The person.
        project_id: The record's project.
        artefact_type: The registered record type.
        record_reviewer: The record's own reviewer (or owner, for a type whose owner reviews), `None` when it has none.

    Returns:
        `True` when the record has no reviewer and the person is the policy's default owner or an effective member of it.
    """
    if record_reviewer is not None:
        return False
    return is_principal_member(db, review_policy(db, project_id, artefact_type).default_owner, user_id)


def _message(adapter: ReviewAdapter, reminder: ReviewReminder, overdue: bool) -> tuple[str, str]:
    """The notification `(title, body)` of a reminder: the adapter's wording, else the engine's."""
    if adapter.message is not None:
        return adapter.message(reminder, overdue)
    return (
        f"Review due: {reminder.title}",
        f"{reminder.code} is due for review by {reminder.due_on.isoformat()}.",
    )


def send_review_reminders(db: Session, today: date | None = None) -> int:
    """The daily reminder sweep over every adapter that hands over its reminders.

    For each record whose reminder window has opened and that has not been reminded for its current due date (separately
    for "due" and "overdue" where the type has both), notifies its reviewer (every active member of a reviewer group), else
    the policy's default owner, else the adapter's fallback or the project managers, and records that the reminder was
    sent. A project where the adapter's module or sub-component is off is skipped. Commits once at the end.

    Args:
        db: An active database session.
        today: The day to compare with; defaults to the UTC date, because the sweep has no caller whose day it could use.

    Returns:
        The number of records reminded.
    """
    today = today or datetime.now(UTC).date()
    now = datetime.now(UTC)
    reminded = 0
    for artefact_type, (module_key, adapter) in sorted(registry.get_review_adapters().items()):
        if adapter.pending_reminders is None or adapter.mark_reminded is None or adapter.notification_type is None:
            continue
        active: dict[uuid.UUID, bool] = {}
        lead_defaults: dict[uuid.UUID, int | None] = {}
        policies: dict[uuid.UUID, ReviewPolicy] = {}
        managers: dict[uuid.UUID, set[uuid.UUID]] = {}
        sent: list[ReminderMark] = []
        for reminder in adapter.pending_reminders(db):
            project_id = reminder.project_id
            scope = project_id or reminder.organization_id
            if scope is None:
                continue
            if scope not in active:
                if project_id is not None:
                    active[scope] = governance_seams.registration_active(db, project_id, module_key, adapter.sub_component)
                    policies[scope] = review_policy(db, project_id, artefact_type) if active[scope] else ReviewPolicy()
                else:
                    active[scope] = module_key == "" or registry.is_module_enabled(db, scope, module_key)
                    policies[scope] = ReviewPolicy()
            if not active[scope]:
                continue
            overdue = adapter.overdue_notification_type is not None and reminder.due_on < today
            if (reminder.overdue_reminded_for if overdue else reminder.reminded_for) == reminder.due_on:
                continue
            if scope not in lead_defaults:
                lead_defaults[scope] = (
                    adapter.default_lead_days if adapter.default_lead_days is not None
                    else db.scalar(select(Project.review_reminder_lead_days_default).where(Project.id == project_id))
                    if project_id is not None else None
                )
            lead = reminder_lead_days(reminder.lead_days, policies[scope], lead_defaults[scope])
            if not reminder_open(reminder.due_on, lead, today):
                continue
            recipient_ids = _recipients(db, adapter, reminder, policies[scope], managers)
            title, body = _message(adapter, reminder, overdue)
            kind = adapter.overdue_notification_type if overdue and adapter.overdue_notification_type else adapter.notification_type
            entity_type, entity_id = reminder.entity or (artefact_type, str(reminder.artefact_id))
            for user in db.scalars(select(User).where(User.id.in_(recipient_ids))) if recipient_ids else ():
                notifications.notify(
                    db, user, notification_type=kind, title=title, body=body, project_id=project_id,
                    entity_type=entity_type, entity_id=entity_id,
                )
            sent.append(ReminderMark(reminder.artefact_id, reminder.due_on, overdue))
        if sent:
            adapter.mark_reminded(db, sent, now)
            reminded += len(sent)
    db.commit()
    return reminded
