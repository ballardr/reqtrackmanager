"""
Module: services.perf_dataset.change_requests

The dataset generator for the core `change_request` type: requests (with their first version, a decision for the
ones that were decided, and a discussion thread) against the project's requirements.

Responsibilities:
- Write `change_requests`, `change_request_versions`, `review_comments` on them, tags and audit events, and the
  project's `change_request` sequence counter, in the proportions the dataset spec states.

Design decisions:
- A modify request targets an approved (locked) requirement, as the application requires; a new-requirement
  request carries the proposed component, category and name.
- Status follows the lifecycle: a decided request has `submitted_at`, `decided_at`, `decided_by` and a note.

Dependencies: `perf_dataset.records` (batch, comments, tags), `models.change_request`.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

from app.models.change_request import ChangeRequest, ChangeRequestVersion, ReviewComment
from app.models.enums import ChangeRequestKind, ChangeRequestStatus, ReviewTargetType
from app.services.change_request_summary import CHANGE_REQUEST_CODE_PREFIX
from app.services.perf_dataset import textgen
from app.services.perf_dataset.context import PerfProjectContext
from app.services.perf_dataset.records import RecordBatch, add_comments, add_tags, created_at, pick_weighted

_STATUS_MIX = (
    (ChangeRequestStatus.DRAFT, 0.2), (ChangeRequestStatus.SUBMITTED, 0.15), (ChangeRequestStatus.IN_REVIEW, 0.1),
    (ChangeRequestStatus.APPROVED, 0.35), (ChangeRequestStatus.REJECTED, 0.1), (ChangeRequestStatus.WITHDRAWN, 0.1),
)


def generate_change_requests(ctx: PerfProjectContext) -> dict[str, int]:
    """Writes the project's change requests.

    Args:
        ctx: The project's context; needs `ctx.shared["requirement"]` and `["requirement_approved"]`.

    Returns:
        Rows written by table name.
    """
    rng = ctx.rng
    requirements = ctx.shared.get("requirement", [])
    approved = ctx.shared.get("requirement_approved", [])
    count = ctx.spec.ratios.count_for("change_request", len(requirements))
    if count == 0 or not requirements:
        return {}
    start = dict(ctx.counts)
    batch = RecordBatch.start(ctx, "change_request", CHANGE_REQUEST_CODE_PREFIX, ChangeRequest)
    category_id, component_id, _prefix = ctx.project.categories[0]
    for _ in range(count):
        creator, created = rng.choice(ctx.user_ids), created_at(rng, max_days=400)
        modify = bool(approved) and rng.random() < 0.7
        status = pick_weighted(rng, _STATUS_MIX)
        decided = status in (ChangeRequestStatus.APPROVED, ChangeRequestStatus.REJECTED)
        submitted = status is not ChangeRequestStatus.DRAFT
        name = textgen.title(rng)
        record_id = batch.new_id()
        batch.add(
            {
                "id": record_id,
                "requirement_id": rng.choice(approved) if modify else None,
                "kind": ChangeRequestKind.MODIFY_REQUIREMENT if modify else ChangeRequestKind.NEW_REQUIREMENT,
                "status": status,
                "submitted_at": created + timedelta(days=1) if submitted else None,
                "decided_at": created + timedelta(days=4) if decided else None,
                "decided_by": rng.choice(ctx.user_ids) if decided else None,
                "decision_note": textgen.sentences(rng, 1) if decided else "",
            },
            creator=creator, at=created, title=name,
        )
        batch.satellite(ChangeRequestVersion, {
            "id": batch.new_id(), "change_request_id": record_id, "version_number": 1,
            "proposed_name": name, "proposed_reasoning": textgen.paragraphs(rng, empty_chance=0.2, short_max=2),
            "proposed_clarification": textgen.paragraphs(rng, empty_chance=0.6, short_max=2),
            "proposed_description": textgen.paragraphs(rng, empty_chance=0.3, short_max=3),
            "proposed_component_id": None if modify else uuid.UUID(component_id),
            "proposed_category_id": None if modify else uuid.UUID(category_id),
            "changed_fields": ["name", "reasoning"] if modify else [],
            "reason": textgen.sentences(rng, rng.randint(1, 2)), "custom_fields": {},
            "created_by": creator, "created_at": created,
        })
        if submitted:
            batch.audit_event(record_id, "submitted", creator, created + timedelta(days=1))
        if decided:
            batch.audit_event(record_id, status.value, rng.choice(ctx.user_ids), created + timedelta(days=4))
    batch.write()
    add_comments(ctx, batch, ReviewComment, "target_id", extra={"target_type": ReviewTargetType.CHANGE_REQUEST})
    add_tags(ctx, batch)
    return {table: ctx.counts.get(table, 0) - start.get(table, 0) for table in ctx.counts}
