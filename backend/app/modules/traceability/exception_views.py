"""
Module: modules.traceability.exception_views

The response shapes of traceability exceptions, built in a fixed number of statements however many rows there are, and
the attachment kit of their comments and evidence.

Responsibilities:
- `rows_out` and `detail_out`: each exception with its record, rule, people and whether it covers.
- `is_open`: awaiting a decision, or in force.

Design decisions:
- The rules in effect are resolved once per project, and records, people and deciders are read in bulk, so a list costs
  the same at any length.
- The record is named only to a caller who may read its type; the router drops the others before this module sees them.

Dependencies: `exception_cover`, `exceptions`, `services.record_summaries`, `services.principals`.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.code_rules import leading_code
from app.models.project import Project
from app.models.user import User
from app.modules import registry
from app.modules.registry import ArtefactSummary
from app.modules.traceability import exception_cover, exceptions, rules
from app.modules.traceability._shared import EXCEPTION_ARTEFACT_TYPE
from app.modules.traceability.enums import ExceptionNoCoverReason, ExceptionStatus
from app.modules.traceability.exception_schemas import (
    ExceptionCommentOut,
    ExceptionDetailOut,
    ExceptionOut,
    ExceptionRecordOut,
)
from app.modules.traceability.models import (
    TraceabilityException,
    TraceabilityExceptionComment,
    TraceabilityExceptionCommentFile,
    TraceabilityExceptionFile,
)
from app.services import module_attachments as att
from app.services import record_summaries
from app.services.client_date import effective_today
from app.services.principals import label_of, principal_labels, principal_ref

ATTACHMENTS = att.AttachmentKit(
    artefact_type=EXCEPTION_ARTEFACT_TYPE, label="Traceability exception", comment_model=TraceabilityExceptionComment,
    comment_file_model=TraceabilityExceptionCommentFile, file_model=TraceabilityExceptionFile, fk="exception_id",
    comment_out=ExceptionCommentOut,
)


def record_summaries_for(
    db: Session, project_id: uuid.UUID, rows: Sequence[TraceabilityException],
) -> dict[tuple[str, uuid.UUID], ArtefactSummary]:
    """The excepted records of the rows, read once per record type."""
    wanted: dict[str, set[uuid.UUID]] = defaultdict(set)
    for row in rows:
        wanted[row.artefact_type].add(row.artefact_id)
    found: dict[tuple[str, uuid.UUID], ArtefactSummary] = {}
    for artefact_type, ids in wanted.items():
        for record_id, summary in record_summaries.read_summaries(db, project_id, artefact_type, sorted(ids)).items():
            found[(artefact_type, record_id)] = summary
    return found


def record_code_and_title(summary: ArtefactSummary | None) -> tuple[str, str]:
    """A record's code and its title from its summary, empty for a record that no longer exists."""
    if summary is None:
        return "", ""
    code = leading_code(summary.label) or ""
    return code, summary.label[len(code):].strip()


def _values(
    row: TraceabilityException, entry: rules.EffectiveRule | None, summary: ArtefactSummary | None,
    people: dict[Any, Any], deciders: dict[uuid.UUID, str], today: Any,
) -> dict[str, Any]:
    code, title = record_code_and_title(summary)
    reason = exception_cover.no_cover_reason(row, entry, today)
    return {
        "id": row.id, "project_id": row.project_id, "unique_code": row.unique_code, "title": row.title,
        "status": row.status,
        "record": ExceptionRecordOut(
            artefact_type=row.artefact_type, artefact_type_label=registry.get_artefact_type_label(row.artefact_type),
            id=row.artefact_id, code=code, label=title, removed=summary is None or summary.is_archived,
        ),
        "rule_id": row.rule_id, "rule_name": row.rule_name if entry is None else entry.rule.name, "reason": row.reason,
        "requester": label_of(people, row.requester_type, row.requester_id),
        "approver": label_of(people, row.approver_type, row.approver_id),
        "expires_on": row.expires_on, "review_date": row.review_date, "creator_id": row.creator_id,
        "decided_by_id": row.decided_by_id, "decided_by_name": deciders.get(row.decided_by_id) if row.decided_by_id else None,
        "decided_at": row.decided_at, "decision_comment": row.decision_comment,
        "covers": reason is None and summary is not None and not summary.is_archived, "no_cover_reason": reason,
        "expired": exception_cover.is_expired(row, today),
        "rule_changed": exception_cover.rule_changed(row, None if entry is None else entry.rule),
        "needs_organisation_approval": entry is not None and entry.enforced, "is_archived": row.is_archived,
        "created_at": row.created_at, "updated_at": row.updated_at,
    }


def _build(db: Session, project: Project, rows: Sequence[TraceabilityException]) -> list[dict[str, Any]]:
    if not rows:
        return []
    entries = exceptions.rule_entries(db, project)
    summaries = record_summaries_for(db, project.id, rows)
    people = principal_labels(db, [
        ref for row in rows for ref in (
            principal_ref(row.requester_type, row.requester_id), principal_ref(row.approver_type, row.approver_id),
        )
    ])
    decider_ids = {row.decided_by_id for row in rows if row.decided_by_id is not None}
    deciders = {
        u.id: u.display_name for u in db.scalars(select(User).where(User.id.in_(decider_ids)))
    } if decider_ids else {}
    today = effective_today()
    return [
        _values(
            row, None if row.rule_id is None else entries.get(row.rule_id),
            summaries.get((row.artefact_type, row.artefact_id)), people, deciders, today,
        )
        for row in rows
    ]


def rows_out(db: Session, project: Project, rows: Sequence[TraceabilityException]) -> list[ExceptionOut]:
    """The list shape of the project's exceptions, in the order given."""
    return [ExceptionOut(**values) for values in _build(db, project, rows)]


def detail_out(db: Session, project: Project, row: TraceabilityException, user: User) -> ExceptionDetailOut:
    """One exception with the actions `user` may take."""
    entry = None if row.rule_id is None else rules.get_rule_in_project(db, project, row.rule_id)
    return ExceptionDetailOut(
        **_build(db, project, [row])[0], actions=exceptions.allowed_actions(db, user, project, row, entry),
    )


def is_open(out: ExceptionOut) -> bool:
    """Awaiting a decision, or approved and not expired: what a list's "Open only" view keeps."""
    if out.is_archived:
        return False
    if out.status == ExceptionStatus.REQUESTED:
        return True
    return out.status == ExceptionStatus.APPROVED and out.no_cover_reason != ExceptionNoCoverReason.EXPIRED
