"""
Module: modules.product_feedback.perf_dataset

The dataset generator for the `enhancement_request` artefact type: project requests with their version history
(including declined ones with a reason), comments, tags, "Requested by" links to Stakeholders, Personas and
Engagements, and a share of duplicates merged into an earlier request.

Responsibilities:
- Write `enhancement_requests`, `enhancement_request_versions`, `enhancement_request_comments`,
  `enhancement_request_merges`, tags, cross-type `artefact_links` and audit events, and the project's
  `enhancement_request` sequence counter.

Design decisions:
- A duplicate is created with the `DUPLICATE` status its merge row implies and points at an earlier, non-duplicate
  request of the batch, so no chain exists.
- Only project-owned requests are generated; the organisation inbox is not covered (its rows belong to the
  organisation, not a project).

Dependencies: `perf_dataset.records`, this module's models.
"""

from __future__ import annotations

from datetime import timedelta

from app.modules.product_feedback.demand import REQUESTED_BY_FORWARD
from app.modules.product_feedback.enums import EnhancementRequestScope, EnhancementRequestStatus
from app.modules.product_feedback.models import (
    EnhancementRequest,
    EnhancementRequestComment,
    EnhancementRequestMerge,
    EnhancementRequestVersion,
)
from app.modules.product_feedback.service import REQUEST_ARTEFACT_TYPE, REQUEST_CODE_PREFIX
from app.services.perf_dataset import textgen
from app.services.perf_dataset.context import PerfProjectContext
from app.services.perf_dataset.core import extra_versions
from app.services.perf_dataset.records import (
    Partner,
    RecordBatch,
    add_comments,
    add_tags,
    created_at,
    link_to_earlier,
    pick_weighted,
)

_S = EnhancementRequestStatus
_STATUS_MIX = (
    (_S.NEW, 0.3), (_S.UNDER_REVIEW, 0.2), (_S.ACCEPTED, 0.2), (_S.DELIVERED, 0.1), (_S.DECLINED, 0.15),
)


def generate_requests(ctx: PerfProjectContext) -> dict[str, int]:
    """Writes the project's enhancement requests and everything hanging off them.

    Args:
        ctx: The project's context.

    Returns:
        Rows written by table name.
    """
    rng = ctx.rng
    count = ctx.spec.ratios.count_for(REQUEST_ARTEFACT_TYPE, len(ctx.shared.get("requirement", [])))
    if count == 0:
        return {}
    start = dict(ctx.counts)
    batch = RecordBatch.start(ctx, REQUEST_ARTEFACT_TYPE, REQUEST_CODE_PREFIX, EnhancementRequest)
    canonicals: list = []
    for _ in range(count):
        creator, created = rng.choice(ctx.user_ids), created_at(rng)
        final = pick_weighted(rng, _STATUS_MIX)
        prior = final
        duplicate_of = None
        if canonicals and final in (_S.NEW, _S.UNDER_REVIEW, _S.ACCEPTED) and rng.random() < 0.08:
            duplicate_of, final = rng.choice(canonicals), _S.DUPLICATE
        archived = rng.random() < 0.03
        record_id = batch.new_id()
        if duplicate_of is None:
            canonicals.append(record_id)
        else:
            batch.satellite(EnhancementRequestMerge, {
                "id": batch.new_id(), "canonical_id": duplicate_of, "duplicate_id": record_id, "prior_status": prior,
                "merged_by": creator, "merged_at": created + timedelta(days=1), "unmerged_by": None, "unmerged_at": None,
                "created_at": created + timedelta(days=1), "updated_at": created + timedelta(days=1),
            })
        title = textgen.title(rng)
        batch.add(
            {"id": record_id, "scope": EnhancementRequestScope.PROJECT, "organization_id": None, "is_archived": archived,
             "archived_at": created + timedelta(days=60) if archived else None,
             "archived_by": creator if archived else None},
            creator=creator, at=created, title=title,
        )
        owner = rng.choice(ctx.user_ids) if rng.random() < 0.6 else None
        extra = extra_versions(rng, ctx.spec.ratios.versions_per_requirement)
        valid_from = created
        for number in range(1, extra + 2):
            last = number == extra + 1
            author = creator if number == 1 else rng.choice(ctx.user_ids)
            next_from = valid_from + timedelta(hours=rng.uniform(1, 24 * 30))
            if number > 1:
                batch.audit_event(record_id, "updated", author, valid_from, {"change_note": "Reworded."})
            batch.satellite(EnhancementRequestVersion, {
                "id": batch.new_id(), "request_id": record_id, "version_number": number, "valid_from": valid_from,
                "valid_to": None if last else next_from, "title": title,
                "description": textgen.paragraphs(rng, empty_chance=0.1, short_max=3),
                "status": final if last else _S.NEW, "owner_type": "user" if owner else None, "owner_id": owner,
                "external_ref_url": None, "external_ref_key": None,
                "decline_reason": textgen.sentences(rng, 1) if last and final == _S.DECLINED else "",
                "change_note": "Initial creation." if number == 1 else "Reworded.", "created_by": author,
                "created_at": valid_from,
            })
            valid_from = next_from
    batch.write()
    add_comments(ctx, batch, EnhancementRequestComment, "request_id")
    add_tags(ctx, batch)
    link_to_earlier(ctx, batch, [
        ("pain_point", 0.3), ("requirement_action", 0.1),
        Partner("stakeholder", 0.3, forward_name=REQUESTED_BY_FORWARD),
        Partner("persona", 0.15, forward_name=REQUESTED_BY_FORWARD),
        Partner("engagement", 0.15, forward_name=REQUESTED_BY_FORWARD),
    ])
    return {table: ctx.counts.get(table, 0) - start.get(table, 0) for table in ctx.counts}
