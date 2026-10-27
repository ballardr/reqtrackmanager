"""
Module: modules.context_strategy.perf_dataset

The dataset generators for the five Context & Strategy artefact types: strategies, future states and guiding
principles (versioned), pain points (with per-persona scores) and open questions.

Responsibilities:
- Write each type's identity rows, version rows where the type has them, pain point scores, comments, tags,
  cross-type links and audit events, and the project's sequence counter for the type.

Design decisions:
- Project-scoped records only: an organisation-scoped strategy, future state or principle belongs to no project, so
  it is not part of a per-project dataset. That is a stated gap of the generator, not of the application.
- Pain point scores are per persona (the persona ids of the same project), using the organisation's real scoring
  levels, so the scoring roll-up reads rows shaped like production ones.
- Each type links outward to types generated before it (`PerfDatasetGenerator.order`).

Dependencies: `perf_dataset.records`, this module's models and enums, `services.scoring`.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from app.modules.context_strategy.enums import (
    FutureStateScope,
    FutureStateStatus,
    GuidingPrinciplePriority,
    GuidingPrincipleScope,
    GuidingPrincipleStatus,
    OpenQuestionPriority,
    OpenQuestionStatus,
    PainPointPriority,
    PainPointStatus,
    StrategyPriority,
    StrategyScope,
    StrategyStatus,
    StrategyTimeHorizon,
)
from app.modules.context_strategy.models import (
    FutureState,
    FutureStateComment,
    FutureStateVersion,
    GuidingPrinciple,
    GuidingPrincipleComment,
    GuidingPrincipleVersion,
    OpenQuestion,
    OpenQuestionComment,
    PainPoint,
    PainPointComment,
    PainPointScore,
    PainPointTypeDefinition,
    ProjectPainPointType,
    Strategy,
    StrategyComment,
    StrategyVersion,
)
from app.modules.context_strategy.scoring import PAIN_POINT_SCORING_SCHEME_KEY
from app.modules.context_strategy.service import (
    FUTURE_STATE_CODE_PREFIX,
    GUIDING_PRINCIPLE_CODE_PREFIX,
    OPEN_QUESTION_CODE_PREFIX,
    PAIN_POINT_CODE_PREFIX,
    STRATEGY_CODE_PREFIX,
)
from app.services.perf_dataset import textgen
from app.services.perf_dataset.context import PerfProjectContext, uuid_from
from app.services.perf_dataset.core import extra_versions
from app.services.perf_dataset.records import (
    RecordBatch,
    add_comments,
    add_tags,
    at_between,
    created_at,
    link_to_earlier,
    pick_weighted,
    project_type_ids,
)
from app.services.scoring import list_levels

STRATEGY, FUTURE_STATE = "strategy", "future_state"
GUIDING_PRINCIPLE, PAIN_POINT, OPEN_QUESTION = "guiding_principle", "pain_point", "open_question"

_LIFECYCLE_MIX = (
    ("draft", 0.2), ("proposed", 0.1), ("under_review", 0.1), ("approved", 0.1), ("active", 0.4), ("superseded", 0.05),
    ("retired", 0.05),
)
_PRINCIPLE_MIX = (("draft", 0.2), ("proposed", 0.1), ("approved", 0.1), ("active", 0.5), ("superseded", 0.05), ("retired", 0.05))
_AXES = ("severity", "frequency", "confidence")
_PRIORITY_MIX = (("low", 0.25), ("medium", 0.5), ("high", 0.25))
_PAIN_STATUS_MIX = tuple((s, w) for s, w in (
    (PainPointStatus.SUBMITTED, 0.25), (PainPointStatus.TRIAGED, 0.15), (PainPointStatus.ACCEPTED, 0.25),
    (PainPointStatus.ADDRESSED, 0.15), (PainPointStatus.CLOSED, 0.1), (PainPointStatus.REJECTED, 0.05), (PainPointStatus.DUPLICATE, 0.05),
))
_QUESTION_MIX = tuple((s, w) for s, w in (
    (OpenQuestionStatus.OPEN, 0.4), (OpenQuestionStatus.INVESTIGATING, 0.2), (OpenQuestionStatus.READY_FOR_DECISION, 0.1),
    (OpenQuestionStatus.RESOLVED, 0.25), (OpenQuestionStatus.WITHDRAWN, 0.05),
))


def _delta(ctx: PerfProjectContext, start: dict[str, int]) -> dict[str, int]:
    return {table: ctx.counts.get(table, 0) - start.get(table, 0) for table in ctx.counts}


def _versioned(
    ctx: PerfProjectContext, *, artefact_type: str, prefix: str, identity: Any, version_model: Any, fk: str,
    comment_model: Any, scope: Any, status_mix: Any, status_enum: Any, content: Any, partners: Any,
) -> dict[str, int]:
    """Shared body of the three versioned types.

    `content(rng, n)` returns the type's text columns for one version (`n` is the version number) and its display
    title for the audit event.
    """
    rng = ctx.rng
    count = ctx.spec.ratios.count_for(artefact_type, len(ctx.shared.get("requirement", [])))
    if count == 0:
        return {}
    start = dict(ctx.counts)
    batch = RecordBatch.start(ctx, artefact_type, prefix, identity)
    for _ in range(count):
        creator, created = rng.choice(ctx.user_ids), created_at(rng)
        final = status_enum(pick_weighted(rng, status_mix))
        archived = rng.random() < 0.03
        record_id = batch.new_id()
        _columns, title = content(rng, 1)
        batch.add(
            {"id": record_id, "scope": scope, "organization_id": None, "is_archived": archived,
             "archived_at": created + timedelta(days=90) if archived else None, "archived_by": creator if archived else None},
            creator=creator, at=created, title=title,
        )
        extra = extra_versions(rng, ctx.spec.ratios.versions_per_requirement)
        valid_from = created
        for number in range(1, extra + 2):
            last = number == extra + 1
            author = creator if number == 1 else rng.choice(ctx.user_ids)
            next_from = valid_from + timedelta(hours=rng.uniform(1, 24 * 30))
            columns, _title = content(rng, number)
            if number > 1:
                batch.audit_event(record_id, "updated", author, valid_from, {"change_note": "Reworded."})
            batch.satellite(version_model, {
                "id": batch.new_id(), fk: record_id, "version_number": number, "valid_from": valid_from,
                "valid_to": None if last else next_from, **columns,
                "status": final if last else status_enum("draft"),
                "change_note": "Initial creation." if number == 1 else "Reworded.", "created_by": author, "created_at": valid_from,
            })
            valid_from = next_from
    batch.write()
    add_comments(ctx, batch, comment_model, fk)
    add_tags(ctx, batch)
    link_to_earlier(ctx, batch, partners)
    return _delta(ctx, start)


def _strategy_content(rng, number):
    title = textgen.title(rng)
    return {
        "title": title, "objective": textgen.sentences(rng, 2), "current_state": textgen.paragraphs(rng, empty_chance=0.2, short_max=2),
        "desired_future_state": textgen.paragraphs(rng, empty_chance=0.2, short_max=2),
        "rationale": textgen.paragraphs(rng, empty_chance=0.2, short_max=3),
        "expected_outcomes": textgen.paragraphs(rng, empty_chance=0.3, short_max=2),
        "constraints": textgen.paragraphs(rng, empty_chance=0.4, short_max=2),
        "measures_of_success": textgen.paragraphs(rng, empty_chance=0.3, short_max=2),
        "priority": StrategyPriority(pick_weighted(rng, _PRIORITY_MIX)),
        "time_horizon": rng.choice(list(StrategyTimeHorizon)),
    }, title


def generate_strategies(ctx: PerfProjectContext) -> dict[str, int]:
    """Writes the project's strategies (see the module docstring)."""
    return _versioned(
        ctx, artefact_type=STRATEGY, prefix=STRATEGY_CODE_PREFIX, identity=Strategy, version_model=StrategyVersion,
        fk="strategy_id", comment_model=StrategyComment, scope=StrategyScope.PROJECT, status_mix=_LIFECYCLE_MIX,
        status_enum=StrategyStatus, content=_strategy_content,
        partners=[("decision", 0.4), ("risk", 0.3), (PAIN_POINT, 0.3)],
    )


def _future_state_content(rng, number):
    title = textgen.title(rng)
    return {
        "title": title, "current_state": textgen.paragraphs(rng, empty_chance=0.2, short_max=2),
        "desired_state": textgen.paragraphs(rng, empty_chance=0.1, short_max=3),
        "target_date": date(2026, 1, 1) + timedelta(days=rng.randrange(0, 900)) if rng.random() < 0.7 else None,
        "outcomes": textgen.paragraphs(rng, empty_chance=0.3, short_max=2),
        "success_measures": textgen.paragraphs(rng, empty_chance=0.3, short_max=2),
        "constraints": textgen.paragraphs(rng, empty_chance=0.4, short_max=2),
        "assumptions": textgen.paragraphs(rng, empty_chance=0.4, short_max=2),
    }, title


def generate_future_states(ctx: PerfProjectContext) -> dict[str, int]:
    """Writes the project's future states."""
    return _versioned(
        ctx, artefact_type=FUTURE_STATE, prefix=FUTURE_STATE_CODE_PREFIX, identity=FutureState, version_model=FutureStateVersion,
        fk="future_state_id", comment_model=FutureStateComment, scope=FutureStateScope.PROJECT, status_mix=_LIFECYCLE_MIX,
        status_enum=FutureStateStatus, content=_future_state_content, partners=[(STRATEGY, 0.6), ("requirement", 0.4)],
    )


def _principle_content_factory(ctx: PerfProjectContext):
    def content(rng, number):
        name = textgen.title(rng)
        owner = rng.choice(ctx.user_ids) if rng.random() < 0.7 else None
        return {
            "name": name, "principle_statement": textgen.sentences(rng, 2), "rationale": textgen.paragraphs(rng, empty_chance=0.2, short_max=2),
            "priority": GuidingPrinciplePriority(pick_weighted(rng, _PRIORITY_MIX)),
            "owner_type": "user" if owner else None, "owner_id": owner,
        }, name

    return content


def generate_guiding_principles(ctx: PerfProjectContext) -> dict[str, int]:
    """Writes the project's guiding principles."""
    return _versioned(
        ctx, artefact_type=GUIDING_PRINCIPLE, prefix=GUIDING_PRINCIPLE_CODE_PREFIX, identity=GuidingPrinciple,
        version_model=GuidingPrincipleVersion, fk="guiding_principle_id", comment_model=GuidingPrincipleComment,
        scope=GuidingPrincipleScope.PROJECT, status_mix=_PRINCIPLE_MIX, status_enum=GuidingPrincipleStatus,
        content=_principle_content_factory(ctx), partners=[("decision", 0.5), (STRATEGY, 0.5)],
    )


def generate_pain_points(ctx: PerfProjectContext) -> dict[str, int]:
    """Writes the project's pain points with per-persona scores."""
    rng, db = ctx.rng, ctx.db
    count = ctx.spec.ratios.count_for(PAIN_POINT, len(ctx.shared.get("requirement", [])))
    type_ids = project_type_ids(ctx, ProjectPainPointType, PainPointTypeDefinition)
    if count == 0 or not type_ids:
        return {}
    start = dict(ctx.counts)
    levels = {axis: [lv.id for lv in rows] for axis, rows in list_levels(db, ctx.organization_uuid, PAIN_POINT_SCORING_SCHEME_KEY).items()}
    personas = ctx.shared.get("persona", [])
    batch = RecordBatch.start(ctx, PAIN_POINT, PAIN_POINT_CODE_PREFIX, PainPoint)
    for _ in range(count):
        creator, created = rng.choice(ctx.user_ids), created_at(rng)
        archived = rng.random() < 0.03
        title = textgen.title(rng)
        owner = rng.choice(ctx.user_ids) if rng.random() < 0.6 else None
        record_id = batch.add(
            {
                "pain_point_type_id": rng.choice(type_ids), "title": title,
                "description": textgen.paragraphs(rng, empty_chance=0.1, short_max=3),
                "source": textgen.sentences(rng, 1), "impact": textgen.paragraphs(rng, empty_chance=0.2, short_max=2),
                "evidence": textgen.paragraphs(rng, empty_chance=0.3, short_max=2),
                "priority": PainPointPriority(pick_weighted(rng, _PRIORITY_MIX)), "status": pick_weighted(rng, _PAIN_STATUS_MIX),
                "owner_type": "user" if owner else None, "owner_id": owner,
                "date_identified": (created + timedelta(days=rng.randint(0, 5))).date(), "is_intentional": rng.random() < 0.05,
                "is_archived": archived, "archived_at": created + timedelta(days=90) if archived else None,
                "archived_by": creator if archived else None,
            },
            creator=creator, at=created, title=title,
        )
        if levels and personas:
            for persona_id in rng.sample(personas, min(rng.choice((0, 1, 2, 3)), len(personas))):
                batch.satellite(PainPointScore, {
                    "id": uuid_from(rng), "pain_point_id": record_id, "target_type": "persona", "target_id": persona_id,
                    **{f"{axis}_level_id": rng.choice(levels[axis]) if levels.get(axis) else None for axis in _AXES},
                    "scored_by": rng.choice(ctx.user_ids), "created_at": at_between(rng, created), "updated_at": created,
                })
    batch.write()
    add_comments(ctx, batch, PainPointComment, "pain_point_id")
    add_tags(ctx, batch)
    link_to_earlier(ctx, batch, [("requirement", 0.5), ("persona", 0.2), ("stakeholder_need", 0.2), ("risk", 0.1)])
    return _delta(ctx, start)


def generate_open_questions(ctx: PerfProjectContext) -> dict[str, int]:
    """Writes the project's open questions."""
    rng = ctx.rng
    count = ctx.spec.ratios.count_for(OPEN_QUESTION, len(ctx.shared.get("requirement", [])))
    if count == 0:
        return {}
    start = dict(ctx.counts)
    batch = RecordBatch.start(ctx, OPEN_QUESTION, OPEN_QUESTION_CODE_PREFIX, OpenQuestion)
    for _ in range(count):
        creator, created = rng.choice(ctx.user_ids), created_at(rng)
        archived = rng.random() < 0.03
        question = textgen.title(rng) + "?"
        owner = rng.choice(ctx.user_ids) if rng.random() < 0.6 else None
        batch.add(
            {
                "question": question, "context": textgen.paragraphs(rng, empty_chance=0.2, short_max=2),
                "evidence": textgen.paragraphs(rng, empty_chance=0.5, short_max=2),
                "priority": OpenQuestionPriority(pick_weighted(rng, _PRIORITY_MIX)), "status": pick_weighted(rng, _QUESTION_MIX),
                "owner_type": "user" if owner else None, "owner_id": owner,
                "due_date": date(2026, 1, 1) + timedelta(days=rng.randrange(0, 700)) if rng.random() < 0.5 else None,
                "is_archived": archived, "archived_at": created + timedelta(days=90) if archived else None,
                "archived_by": creator if archived else None,
            },
            creator=creator, at=created, title=question,
        )
    batch.write()
    add_comments(ctx, batch, OpenQuestionComment, "open_question_id")
    add_tags(ctx, batch)
    link_to_earlier(ctx, batch, [("decision", 0.5), ("requirement", 0.3), ("risk", 0.2)])
    return _delta(ctx, start)

