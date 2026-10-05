"""
Module: modules.context_strategy.pain_point_scores

Per-persona Pain Point scoring (Module 1 Phase 11): persisting a Pain
Point's Severity/Frequency/Confidence ratings (`PainPointScore`) and rolling
them up into one score and a Blocker flag under a model and roll-up method
chosen when viewing.

Responsibilities:
- `set_pain_point_scores`: validates and replaces a Pain Point's score set
  (either one "all personas" row or per-persona rows, never both).
- `load_scoring_context` / `summarise` / `build_pain_point_scoring`: the
  roll-up maths, built on core's generic `services.scoring` (levels, bands,
  `compute_score`) and the generic `registry.get_scoring_targets` hook, so
  this module never imports Module 2.
- The scheme's `count_level_usage`/`reassign_level_usage` hooks live in
  `scoring.py` (they need only the model); the maths live here.

Design decisions (all Decided by: Agent unless stated; Phase 9 Q5 and
Phase 11 scope are Decided by: User):
- Roll-up methods: weighted average (default), worst case, plain average.
  Only personas scored under the chosen model count; an unscored persona is
  excluded, never zero, so one scored persona of five shows that persona's
  value (Phase 9 Q5, User). Weighted average is taken over the normalised
  score, which is equivalent to averaging raw scores because a model's
  maximum is a constant.
- A persona with no weight among others that have one gets the mean of the
  set weights (neutral), so it neither dominates nor vanishes; if none has a
  weight, all are equal.
- A retired persona (`ScoringTarget.is_active` false) stays visible but is
  skipped by the roll-up and the Blocker flag. A target the provider no
  longer lists (persona deleted/hidden, or Module 2 off) is `unavailable`:
  it still counts, unweighted and unlabelled, and the summary reports
  `personas_degraded` so the UI/reports can say so.
- The Blocker flag keys off the top Severity level on any counted score row,
  independent of the model and roll-up, so it can't be averaged away.
- Scoring is a manager-tier action (the router enforces it): Pain Point
  creation is broad, but prioritisation isn't.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.project import Project
from app.models.scoring import ScoringLevel
from app.models.user import User
from app.modules.context_strategy.models import PainPoint, PainPointScore
from app.modules.context_strategy.scoring import PAIN_POINT_SCORING_SCHEME_KEY
from app.modules.registry import ScoringModelDefinition, ScoringSchemeDefinition, ScoringTarget, get_scoring_targets
from app.services.audit import log_event
from app.services.scoring import (
    BandValue,
    ScoreResult,
    band_for,
    compute_score,
    get_registered_scheme,
    list_levels,
    max_axis_weights,
    resolve_effective_bands,
    resolve_effective_model,
)

PERSONA_TARGET_TYPE = "persona"
_AXIS_KEYS = ("severity", "frequency", "confidence")
SEVERITY_AXIS = "severity"


class RollupMethod(str, Enum):
    """How per-persona scores combine into one (Phase 9 Q5)."""

    WEIGHTED_AVERAGE = "weighted_average"
    WORST_CASE = "worst_case"
    AVERAGE = "average"


class TargetStatus(str, Enum):
    """How a score row's target resolves right now."""

    ALL = "all"  # the all-personas row
    ACTIVE = "active"
    INACTIVE = "inactive"  # listed but retired: shown, not counted
    UNAVAILABLE = "unavailable"  # no longer listed: counted unweighted


@dataclass(frozen=True)
class ScoreEntryInput:
    """One requested row of a Pain Point's score set.

    Attributes:
        target_id: The persona scored for, or `None` for "all personas".
        severity_level_id / frequency_level_id / confidence_level_id: Chosen
            levels, `None` = not scored on that axis.
    """

    target_id: uuid.UUID | None
    severity_level_id: uuid.UUID | None = None
    frequency_level_id: uuid.UUID | None = None
    confidence_level_id: uuid.UUID | None = None


@dataclass
class ScoringContext:
    """Everything needed to score the Pain Points of one project.

    Attributes:
        project: The project.
        scheme: The registered `pain_point` scheme.
        levels_by_id: The org's levels for the scheme, by id.
        max_weights: Each axis's top level weight.
        top_severity_weight: The highest Severity weight (the Blocker level).
        default_model_key / default_model_source: The project's resolved
            default model and where it came from.
        targets: The project's persona scoring targets by id (empty when
            Module 2 or its persona sub-component is off).
    """

    project: Project
    scheme: ScoringSchemeDefinition
    levels_by_id: dict[uuid.UUID, ScoringLevel]
    levels_by_axis: dict[str, list[ScoringLevel]]
    max_weights: dict[str, Decimal]
    top_severity_weight: Decimal | None
    default_model_key: str
    default_model_source: str
    targets: dict[uuid.UUID, ScoringTarget]


@dataclass
class EntrySummary:
    """One score row, resolved.

    Attributes:
        row: The stored row.
        label: The target's name, or `None` (all personas / unavailable).
        weight: The target's persona weight, or `None`.
        target_status: See `TargetStatus`.
        score: The row's score under the chosen model, or `None` (not scored
            under this model).
        is_blocker: Whether Severity is the top level on this row.
    """

    row: PainPointScore
    label: str | None
    weight: float | None
    target_status: TargetStatus
    score: ScoreResult | None
    is_blocker: bool


@dataclass
class PainPointScoringSummary:
    """A Pain Point's roll-up under one model and method.

    Attributes:
        pain_point_id: The Pain Point.
        scope: `"none"` (no rows), `"all_personas"` or `"per_persona"`.
        entries: Resolved rows.
        score: The rolled-up score, or `None` if nothing is scored under the
            model.
        counted: Rows that fed the roll-up.
        is_blocker: Any counted row is at the top Severity level.
        blocker_labels: Names of the blocked personas (empty for an
            all-personas blocker or unlabelled targets).
        personas_degraded: Some rows' personas can't be resolved.
    """

    pain_point_id: uuid.UUID
    scope: str
    entries: list[EntrySummary] = field(default_factory=list)
    score: ScoreResult | None = None
    counted: int = 0
    is_blocker: bool = False
    blocker_labels: list[str] = field(default_factory=list)
    personas_degraded: bool = False


# --- Context -----------------------------------------------------------------


def load_scoring_context(db: Session, project: Project) -> ScoringContext:
    """Loads the scheme, org levels, default model and persona targets for
    scoring in `project`.

    Raises:
        HTTPException: 404 if no module registers the `pain_point` scheme.
    """
    scheme = get_registered_scheme(PAIN_POINT_SCORING_SCHEME_KEY).scheme
    levels_by_axis = list_levels(db, project.organization_id, scheme.key)
    default_model_key, default_source = resolve_effective_model(db, project.organization_id, scheme, project.id)
    max_weights = max_axis_weights(levels_by_axis)
    return ScoringContext(
        project=project, scheme=scheme,
        levels_by_id={lvl.id: lvl for levels in levels_by_axis.values() for lvl in levels},
        levels_by_axis=levels_by_axis, max_weights=max_weights,
        top_severity_weight=max_weights.get(SEVERITY_AXIS),
        default_model_key=default_model_key, default_model_source=default_source,
        targets={t.id: t for t in get_scoring_targets(db, project.id, PERSONA_TARGET_TYPE)},
    )


def resolve_model(ctx: ScoringContext, model_key: str | None) -> ScoringModelDefinition:
    """Returns the requested model, or the context's default when `None`.

    Raises:
        HTTPException: 400 for an unknown model key.
    """
    model = ctx.scheme.model(model_key or ctx.default_model_key)
    if model is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown scoring model '{model_key}'.")
    return model


# --- Writing -----------------------------------------------------------------


def list_pain_point_scores(db: Session, pain_point_id: uuid.UUID) -> list[PainPointScore]:
    """Returns a Pain Point's stored score rows (all-personas row first)."""
    return list(db.scalars(
        select(PainPointScore).where(PainPointScore.pain_point_id == pain_point_id)
        .order_by(PainPointScore.target_id.is_(None).desc(), PainPointScore.created_at)
    ).all())


def _validate_level(ctx: ScoringContext, axis_key: str, level_id: uuid.UUID | None) -> None:
    """Raises 400 unless `level_id` is `None` or a level of this org's `axis_key`."""
    if level_id is None:
        return
    level = ctx.levels_by_id.get(level_id)
    if level is None or level.axis_key != axis_key:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Invalid {axis_key} level.")


def set_pain_point_scores(
    db: Session, ctx: ScoringContext, pain_point: PainPoint, entries: list[ScoreEntryInput], actor: User,
) -> list[PainPointScore]:
    """Replaces a Pain Point's score set with `entries` (flushed, not
    committed) and audit-logs the change if anything changed.

    Entries with no level chosen are dropped. At most one row per target;
    the all-personas row (`target_id` None) can't coexist with persona rows.
    A persona must be one of the project's current scoring targets, and a
    retired one can only be kept if it already has a row.

    Raises:
        HTTPException: 400 for a duplicate target, an all-personas row mixed
            with persona rows, an unknown/inactive persona, or a level that
            isn't this org's level for that axis; 409 if a concurrent save or
            level deletion collides with this one.
    """
    kept = [e for e in entries if any(getattr(e, f"{axis}_level_id") for axis in _AXIS_KEYS)]
    target_ids = [e.target_id for e in kept]
    if len(set(target_ids)) != len(target_ids):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Each persona can be scored once.")
    if None in target_ids and len(kept) > 1:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Score either all personas together or each persona separately, not both.",
        )
    existing = {row.target_id: row for row in list_pain_point_scores(db, pain_point.id)}
    for entry in kept:
        for axis in _AXIS_KEYS:
            _validate_level(ctx, axis, getattr(entry, f"{axis}_level_id"))
        if entry.target_id is not None:
            target = ctx.targets.get(entry.target_id)
            if target is None:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "That persona isn't available to score in this project.")
            if not target.is_active and entry.target_id not in existing:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "A retired persona can't be newly scored.")

    changed = False
    wanted = {e.target_id: e for e in kept}
    for target_id, row in existing.items():
        if target_id not in wanted:
            db.delete(row)
            changed = True
    for target_id, entry in wanted.items():
        row = existing.get(target_id)
        if row is None:
            db.add(PainPointScore(
                pain_point_id=pain_point.id, target_type=PERSONA_TARGET_TYPE if target_id else None,
                target_id=target_id, scored_by=actor.id,
                severity_level_id=entry.severity_level_id, frequency_level_id=entry.frequency_level_id,
                confidence_level_id=entry.confidence_level_id,
            ))
            changed = True
            continue
        row_changed = False
        for axis in _AXIS_KEYS:
            column = f"{axis}_level_id"
            if getattr(row, column) != getattr(entry, column):
                setattr(row, column, getattr(entry, column))
                row_changed = True
        if row_changed:
            row.scored_by = actor.id
            changed = True
    try:
        db.flush()
    except IntegrityError as exc:  # concurrent save of the same Pain Point, or a level removed mid-save
        db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, "These scores conflict with a concurrent update; reload and retry.",
        ) from exc
    if changed:
        log_event(
            db, entity_type="pain_point", entity_id=pain_point.id, action="scored", actor_id=actor.id,
            project_id=pain_point.project_id,
            detail={"all_personas": None in wanted, "scored_targets": len([t for t in wanted if t is not None])},
        )
    return list_pain_point_scores(db, pain_point.id)


# --- Maths -------------------------------------------------------------------


def _row_weights(ctx: ScoringContext, row: PainPointScore) -> dict[str, Decimal | None]:
    """Maps each axis to the weight of the row's chosen level (`None` = unscored)."""
    out: dict[str, Decimal | None] = {}
    for axis in _AXIS_KEYS:
        level = ctx.levels_by_id.get(getattr(row, f"{axis}_level_id"))
        out[axis] = level.weight if level is not None else None
    return out


def _resolve_entry(
    ctx: ScoringContext, row: PainPointScore, model: ScoringModelDefinition, bands: list[BandValue],
) -> EntrySummary:
    """Resolves one stored row against its target and the chosen model."""
    weights = _row_weights(ctx, row)
    severity = weights.get(SEVERITY_AXIS)
    is_blocker = severity is not None and ctx.top_severity_weight is not None and severity == ctx.top_severity_weight
    score = compute_score(model, weights, ctx.max_weights, bands)
    if row.target_id is None:
        return EntrySummary(row, None, None, TargetStatus.ALL, score, is_blocker)
    target = ctx.targets.get(row.target_id)
    if target is None:
        return EntrySummary(row, None, None, TargetStatus.UNAVAILABLE, score, is_blocker)
    state = TargetStatus.ACTIVE if target.is_active else TargetStatus.INACTIVE
    return EntrySummary(row, target.label, target.weight, state, score, is_blocker)


def _mean_weight_fill(entries: list[EntrySummary]) -> list[Decimal]:
    """Returns each entry's roll-up weight: its own, else the mean of the set
    weights, else 1 for everyone."""
    set_weights = [Decimal(str(e.weight)) for e in entries if e.weight is not None]
    fill = sum(set_weights) / len(set_weights) if set_weights else Decimal(1)
    return [Decimal(str(e.weight)) if e.weight is not None else fill for e in entries]


def rollup_scores(
    ctx: ScoringContext, entries: list[EntrySummary], model: ScoringModelDefinition,
    method: RollupMethod, bands: list[BandValue],
) -> ScoreResult | None:
    """Combines the scored entries under `method`, or `None` if none is scored."""
    scored = [e for e in entries if e.score is not None]
    if not scored:
        return None
    maximum = Decimal(1)
    for axis_key in model.axis_keys:
        maximum *= ctx.max_weights[axis_key]
    if method is RollupMethod.WORST_CASE:
        worst = max(scored, key=lambda e: e.score.normalised)  # type: ignore[union-attr]
        return worst.score
    if method is RollupMethod.AVERAGE:
        weights = [Decimal(1)] * len(scored)
    else:
        weights = _mean_weight_fill(scored)
    raw = sum((w * e.score.raw for w, e in zip(weights, scored, strict=False)), Decimal(0)) / sum(weights)  # type: ignore[union-attr]
    normalised = float(raw / maximum)
    return ScoreResult(raw=raw, normalised=normalised, band=band_for(normalised, bands))


def summarise(
    ctx: ScoringContext, pain_point_id: uuid.UUID, rows: list[PainPointScore], model: ScoringModelDefinition,
    method: RollupMethod, bands: list[BandValue],
) -> PainPointScoringSummary:
    """Rolls a Pain Point's rows up under `model` and `method`."""
    summary = PainPointScoringSummary(pain_point_id=pain_point_id, scope="none")
    if not rows:
        return summary
    summary.entries = [_resolve_entry(ctx, row, model, bands) for row in rows]
    summary.scope = "all_personas" if any(e.target_status is TargetStatus.ALL for e in summary.entries) else "per_persona"
    counted = [e for e in summary.entries if e.target_status is not TargetStatus.INACTIVE]
    summary.counted = len(counted)
    summary.personas_degraded = any(e.target_status is TargetStatus.UNAVAILABLE for e in summary.entries)
    summary.score = rollup_scores(ctx, counted, model, method, bands)
    blockers = [e for e in counted if e.is_blocker]
    summary.is_blocker = bool(blockers)
    summary.blocker_labels = sorted(e.label for e in blockers if e.label)
    return summary


def build_pain_point_scoring(
    db: Session, ctx: ScoringContext, pain_points: list[PainPoint], model: ScoringModelDefinition,
    method: RollupMethod,
) -> list[PainPointScoringSummary]:
    """Summarises many Pain Points of one project in a single pass (one
    query for all score rows).

    Returns:
        One summary per Pain Point, in input order.
    """
    bands, _ = resolve_effective_bands(db, ctx.project.organization_id, ctx.scheme, model.key, ctx.project.id)
    rows_by_pp: dict[uuid.UUID, list[PainPointScore]] = {}
    if pain_points:
        for row in db.scalars(
            select(PainPointScore).where(PainPointScore.pain_point_id.in_([p.id for p in pain_points]))
            .order_by(PainPointScore.target_id.is_(None).desc(), PainPointScore.created_at)
        ).all():
            rows_by_pp.setdefault(row.pain_point_id, []).append(row)
    return [summarise(ctx, p.id, rows_by_pp.get(p.id, []), model, method, bands) for p in pain_points]
