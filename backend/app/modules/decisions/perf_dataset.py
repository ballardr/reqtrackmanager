"""
Module: modules.decisions.perf_dataset

The dataset generator for the `decision` artefact type: decisions with an owner, a decision maker once decided,
comments, tags, and links to requirements and risks.

Responsibilities:
- Write `decisions`, `decision_comments`, cross-type `artefact_links`, tags and audit events, and the project's
  `decision` sequence counter.

Design decisions:
- A decision carries its content on the row (it has no version table), so one record is one row.
- The decision type is one of the project's own types, or its nearest ancestor's when the project has none (the
  fallback the application applies to its decision types).

Dependencies: `perf_dataset.records`, this module's models, `services.project_hierarchy`.
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select

from app.modules.decisions.enums import DecisionStatus
from app.modules.decisions.export import DECISION_CODE_PREFIX
from app.modules.decisions.models import Decision, DecisionComment, DecisionTypeDefinition
from app.modules.decisions.service import DECISION_ARTEFACT_TYPE
from app.services.perf_dataset import textgen
from app.services.perf_dataset.context import PerfProjectContext
from app.services.perf_dataset.records import RecordBatch, add_comments, add_tags, created_at, link_to_earlier, pick_weighted
from app.services.project_hierarchy import get_project_chain_ids

_STATUS_MIX = (
    (DecisionStatus.DRAFT, 0.15), (DecisionStatus.PROPOSED, 0.15), (DecisionStatus.UNDER_REVIEW, 0.1),
    (DecisionStatus.APPROVED, 0.45), (DecisionStatus.REJECTED, 0.08), (DecisionStatus.SUPERSEDED, 0.07),
)


def generate_decisions(ctx: PerfProjectContext) -> dict[str, int]:
    """Writes the project's decisions.

    Args:
        ctx: The project's context.

    Returns:
        Rows written by table name.
    """
    rng, db = ctx.rng, ctx.db
    count = ctx.spec.ratios.count_for("decision", len(ctx.shared.get("requirement", [])))
    if count == 0:
        return {}
    type_ids: list = []
    for project_id in get_project_chain_ids(db, ctx.project_uuid):
        type_ids = list(db.scalars(select(DecisionTypeDefinition.id).where(DecisionTypeDefinition.project_id == project_id)))
        if type_ids:
            break
    if not type_ids:
        return {}
    start = dict(ctx.counts)
    batch = RecordBatch.start(ctx, DECISION_ARTEFACT_TYPE, DECISION_CODE_PREFIX, Decision)
    for _ in range(count):
        creator, created = rng.choice(ctx.user_ids), created_at(rng)
        status = pick_weighted(rng, _STATUS_MIX)
        decided = status in (DecisionStatus.APPROVED, DecisionStatus.REJECTED, DecisionStatus.SUPERSEDED)
        archived = rng.random() < 0.03
        title = textgen.title(rng)
        maker = rng.choice(ctx.user_ids) if decided or rng.random() < 0.3 else None
        record_id = batch.add(
            {
                "title": title, "decision_statement": textgen.sentences(rng, rng.randint(1, 3)),
                "decision_type_id": rng.choice(type_ids), "status": status,
                "decision_date": (created + timedelta(days=rng.randint(1, 60))).date() if decided else None,
                "decision_maker_type": "user" if maker else None, "decision_maker_id": maker,
                "owner_type": "user", "owner_id": rng.choice(ctx.user_ids),
                "context": textgen.paragraphs(rng, empty_chance=0.1, short_max=3),
                "options_considered": textgen.paragraphs(rng, empty_chance=0.2, short_max=3),
                "chosen_option": textgen.sentences(rng, 1) if decided else None,
                "rationale": textgen.paragraphs(rng, empty_chance=0.2, short_max=3),
                "consequences": textgen.paragraphs(rng, empty_chance=0.3, short_max=2),
                "assumptions": textgen.paragraphs(rng, empty_chance=0.4, short_max=2),
                "constraints": textgen.paragraphs(rng, empty_chance=0.5, short_max=2),
                "is_archived": archived, "archived_at": created + timedelta(days=90) if archived else None,
                "archived_by": creator if archived else None,
            },
            creator=creator, at=created, title=title,
        )
        if decided:
            batch.audit_event(record_id, status.value, maker, created + timedelta(days=5))
    batch.write()
    add_comments(ctx, batch, DecisionComment, "decision_id")
    add_tags(ctx, batch)
    link_to_earlier(ctx, batch, [("requirement", 0.5), ("risk", 0.3), ("change_request", 0.2)])
    return {table: ctx.counts.get(table, 0) - start.get(table, 0) for table in ctx.counts}
