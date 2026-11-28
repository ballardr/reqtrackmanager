"""
Module: modules.traceability.exception_cover

Whether a traceability exception covers its rule for its record, and which exceptions cover the records a status
computation is judging.

Responsibilities:
- Digest a rule's logic (`rule_fingerprint`) so an edit after approval can be reported (`rule_changed`).
- Say why an exception does not cover, or that it does (`no_cover_reason`).
- Read, in one statement, the exceptions covering a set of records (`covers_for`).

Design decisions:
- Cover is computed each time and never stored: expiry, archiving, the rule being deleted, hidden or switched off, and the
  rule becoming one an organisation enforces all end it without a write.
- A rule of an Enforced profile is covered only by an exception approved with the organisation-level right, so a project
  cannot waive an organisation's requirement, including by approving before the profile was enforced.
- An edit to a rule's logic does not end the cover; it is reported with the exception so a person can revoke it. The name,
  description and enforcement level are not part of the logic.
- An expiry date is the last day covered, judged against the caller's day (`services.client_date`).
- With the `traceability_exceptions` part off nothing is covered; the records are kept.

Dependencies: `models`, `rules` (the rules in effect), `modules.registry`, `services.client_date`.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from datetime import date

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.modules import registry
from app.modules.traceability import rules
from app.modules.traceability._shared import TRACEABILITY_EXCEPTIONS, TRACEABILITY_MODULE_KEY
from app.modules.traceability.enums import ExceptionNoCoverReason, ExceptionStatus
from app.modules.traceability.models import GovernanceTraceabilityRule, TraceabilityException
from app.services.client_date import effective_today


@dataclass(frozen=True)
class Cover:
    """An exception that covers one rule for one record.

    Attributes:
        exception_id: The exception.
        unique_code: Its code.
        title: Its title.
        expires_on: The last day it covers, or `None`.
        rule_changed: The rule's logic differs from what was approved.
    """

    exception_id: uuid.UUID
    unique_code: str
    title: str
    expires_on: date | None
    rule_changed: bool


def rule_fingerprint(rule: GovernanceTraceabilityRule) -> str:
    """The SHA-256 digest of the parts of a rule that decide which records meet it."""
    logic = [rule.source_type, rule.source_subtype, rule.applies_when, rule.requires]
    return hashlib.sha256(json.dumps(logic, sort_keys=True, default=str).encode()).hexdigest()


def rule_changed(exception: TraceabilityException, rule: GovernanceTraceabilityRule | None) -> bool:
    """Whether the rule's logic differs from what the exception was approved against (`False` when never approved or the
    rule is gone, which `no_cover_reason` reports)."""
    if rule is None or exception.approved_fingerprint is None:
        return False
    return rule_fingerprint(rule) != exception.approved_fingerprint


def is_expired(exception: TraceabilityException, today: date) -> bool:
    """Whether the last day the exception covers is before `today`."""
    return exception.expires_on is not None and exception.expires_on < today


def no_cover_reason(
    exception: TraceabilityException, entry: rules.EffectiveRule | None, today: date,
) -> ExceptionNoCoverReason | None:
    """Why an exception does not cover its rule.

    Args:
        exception: The exception.
        entry: The rule as it is in effect for the project, or `None` when the project does not hold it.
        today: The caller's day.

    Returns:
        The first reason that applies, or `None` when the exception covers.
    """
    if exception.is_archived:
        return ExceptionNoCoverReason.ARCHIVED
    if exception.status != ExceptionStatus.APPROVED:
        return ExceptionNoCoverReason.NOT_APPROVED
    if is_expired(exception, today):
        return ExceptionNoCoverReason.EXPIRED
    if entry is None or not entry.active:
        return ExceptionNoCoverReason.RULE_REMOVED
    if entry.enforced and not exception.org_approved:
        return ExceptionNoCoverReason.NEEDS_ORGANISATION_APPROVAL
    return None


def part_in_effect(db: Session, project_id: uuid.UUID) -> bool:
    """Whether the project's `traceability_exceptions` part is in effect."""
    return registry.is_module_subcomponent_enabled(db, project_id, TRACEABILITY_MODULE_KEY, TRACEABILITY_EXCEPTIONS)


def covers_for(
    db: Session, project_id: uuid.UUID, artefact_type: str, record_ids: Collection[uuid.UUID],
    entries: Mapping[uuid.UUID, rules.EffectiveRule], today: date | None = None,
) -> dict[tuple[uuid.UUID, uuid.UUID], Cover]:
    """The covering exception of each record and rule that has one.

    Args:
        db: Active session (read only).
        project_id: The project.
        artefact_type: The records' type.
        record_ids: The records being judged.
        entries: The project's rules in effect, by rule id.
        today: The day expiry is judged against; the caller's day when `None`.

    Returns:
        `{(record id, rule id): Cover}`. Where several exceptions cover one record and rule, one approved against the
        rule as it reads now is preferred, then the latest approval.
    """
    if not record_ids or not entries or not part_in_effect(db, project_id):
        return {}
    day = today or effective_today()
    rows = db.scalars(
        select(TraceabilityException).where(
            TraceabilityException.project_id == project_id,
            TraceabilityException.artefact_type == artefact_type,
            TraceabilityException.artefact_id.in_(list(record_ids)),
            TraceabilityException.rule_id.in_(list(entries)),
            TraceabilityException.status == ExceptionStatus.APPROVED,
            TraceabilityException.is_archived.is_(False),
            or_(TraceabilityException.expires_on.is_(None), TraceabilityException.expires_on >= day),
        ).order_by(TraceabilityException.decided_at, TraceabilityException.unique_code)
    )
    found: dict[tuple[uuid.UUID, uuid.UUID], Cover] = {}
    for row in rows:
        if row.rule_id is None:
            continue
        entry = entries[row.rule_id]
        if no_cover_reason(row, entry, day) is not None:
            continue
        changed = rule_changed(row, entry.rule)
        key = (row.artefact_id, row.rule_id)
        if key in found and changed and not found[key].rule_changed:
            continue
        found[key] = Cover(row.id, row.unique_code, row.title, row.expires_on, changed)
    return found
