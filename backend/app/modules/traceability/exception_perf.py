"""
Module: modules.traceability.exception_perf

The dataset generator of `traceability_exception`: for each project one Required rule on requirements and exceptions to it
for a sample of the requirements, most approved, with comments, tags and audit events.

Responsibilities:
- `generate_exceptions`, registered as the type's `PerfDatasetGenerator`.

Design decisions:
- An approved row carries the digest of the generated rule, so the status computation reads it as covering and unchanged.

Dependencies: `perf_dataset.records`, `models`, `rule_tree`, `exception_cover`.
"""

from __future__ import annotations

from datetime import date, timedelta

from app.modules.traceability import exception_cover, rule_tree
from app.modules.traceability._shared import EXCEPTION_ARTEFACT_TYPE, EXCEPTION_CODE_PREFIX
from app.modules.traceability.enums import ExceptionStatus, RuleLevel
from app.modules.traceability.models import (
    GovernanceTraceabilityRule,
    TraceabilityException,
    TraceabilityExceptionComment,
)
from app.services.perf_dataset import textgen
from app.services.perf_dataset.context import ANCHOR, PerfProjectContext, insert_rows
from app.services.perf_dataset.records import (
    RecordBatch,
    add_comments,
    add_tags,
    created_at,
    pick_weighted,
)

_STATUS_MIX = (
    (ExceptionStatus.APPROVED, 0.7), (ExceptionStatus.REQUESTED, 0.2), (ExceptionStatus.REJECTED, 0.04),
    (ExceptionStatus.WITHDRAWN, 0.03), (ExceptionStatus.REVOKED, 0.03),
)
_REQUIRES = {"op": "link", "targets": [{"artefact_type": "requirement"}]}


def _rule(ctx: PerfProjectContext, batch: RecordBatch) -> GovernanceTraceabilityRule:
    """Writes the project's rule; the exceptions are to it."""
    requires = rule_tree.to_json(rule_tree.parse_requires(_REQUIRES))
    rule = GovernanceTraceabilityRule(
        id=batch.new_id(), profile_id=None, project_id=ctx.project_uuid, name="Requirements trace to a requirement",
        description="", source_type="requirement", source_subtype=None, level=RuleLevel.REQUIRED.value, enabled=True,
        sort_order=0, applies_when=None, requires=requires, schema_version=rule_tree.SCHEMA_VERSION, created_at=ANCHOR,
        updated_at=ANCHOR,
    )
    columns = {c.name: getattr(rule, c.name) for c in GovernanceTraceabilityRule.__table__.columns}
    ctx.add_count(GovernanceTraceabilityRule.__tablename__, insert_rows(ctx.db, GovernanceTraceabilityRule, [columns]))
    return rule


def generate_exceptions(ctx: PerfProjectContext) -> dict[str, int]:
    """Writes the project's rule and exceptions.

    Args:
        ctx: The project's context; needs `ctx.shared["requirement"]`.

    Returns:
        Rows written by table name.
    """
    rng = ctx.rng
    requirements = ctx.shared.get("requirement", [])
    count = min(ctx.spec.ratios.count_for(EXCEPTION_ARTEFACT_TYPE, len(requirements)), len(requirements))
    if count == 0:
        return {}
    start = dict(ctx.counts)
    batch = RecordBatch.start(ctx, EXCEPTION_ARTEFACT_TYPE, EXCEPTION_CODE_PREFIX, TraceabilityException)
    rule = _rule(ctx, batch)
    fingerprint = exception_cover.rule_fingerprint(rule)
    for requirement_id in rng.sample(requirements, count):
        creator, created = rng.choice(ctx.user_ids), created_at(rng)
        status = pick_weighted(rng, _STATUS_MIX)
        approved = status is ExceptionStatus.APPROVED
        decided = status in (ExceptionStatus.APPROVED, ExceptionStatus.REJECTED, ExceptionStatus.REVOKED)
        title = textgen.title(rng)
        batch.add(
            {
                "id": batch.new_id(), "is_archived": False, "archived_at": None, "archived_by": None, "title": title,
                "artefact_type": "requirement", "artefact_id": requirement_id, "rule_id": rule.id, "rule_name": rule.name,
                "reason": textgen.paragraphs(rng, empty_chance=0.0, short_max=2),
                "requester_type": "user", "requester_id": creator, "approver_type": None, "approver_id": None,
                "status": status,
                "expires_on": date(2026, 1, 1) + timedelta(days=rng.randrange(0, 900)) if rng.random() < 0.5 else None,
                "review_date": date(2026, 1, 1) + timedelta(days=rng.randrange(0, 700))
                if not batch.ids or rng.random() < 0.3 else None,
                "decided_by_id": rng.choice(ctx.user_ids) if decided else None,
                "decided_at": created + timedelta(days=2) if decided else None,
                "decision_comment": textgen.sentences(rng, 1) if decided else "",
                "approved_fingerprint": fingerprint if approved else None, "org_approved": False,
                "review_due_notified_for": None, "review_overdue_notified_for": None,
            },
            creator=creator, at=created, title=title,
        )
    batch.write()
    add_comments(ctx, batch, TraceabilityExceptionComment, "exception_id")
    add_tags(ctx, batch)
    return {table: ctx.counts.get(table, 0) - start.get(table, 0) for table in ctx.counts}
