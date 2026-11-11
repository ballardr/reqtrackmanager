"""
Module: modules.context_strategy.pain_point_scores

Pain Point scoring: persisting a Pain Point's ratings (`PainPointScore`, one
`PainPointScoreAxis` row per scoring axis) and rolling them up into one score
and a Blocker flag under a model and roll-up method chosen when viewing.

Responsibilities:
- `set_pain_point_scores`: validates and replaces a Pain Point's score set (a
  General row plus the personas that differ from it).
- `score_level_ids` / `assign_score_level_ids`: the one place that knows how a
  row stores its levels; every reader and writer goes through them.
- `load_scoring_context` / `summarise` / `build_pain_point_scoring`: the
  roll-up maths, built on core's generic `services.scoring` (levels, bands,
  `compute_score`), the *effective* scheme (`services.scoring_custom`, so an
  organisation's or project's own criteria score like the registered ones) and
  the generic `registry.get_scoring_targets` hook, so this module never
  imports Stakeholders & Personas.
- The scheme's `count_level_usage`/`reassign_level_usage` hooks live in
  `scoring.py` (they need only the model); the maths live here.

Design decisions (all Decided by: Agent unless stated; the General row, the
unscored-persona rule and the roll-up scope are Decided by: User):
- Each criterion is scored either per persona or for the whole Pain Point
  (`ScoringAxisDefinition.per_target`). The General row holds every
  whole-Pain-Point value and the default for per-persona criteria; a persona
  row holds per-persona criteria only and overrides General for that persona,
  so the panel lists only the personas that differ (User). A persona's score is
  its own value on a per-persona criterion, else General's; a whole-Pain-Point
  criterion is General's for every persona.
- Roll-up methods: weighted average (default), worst case, plain average.
  Only personas scored under the chosen model count; an unscored persona is
  excluded, never zero, so one scored persona of five shows that persona's
  value (User). With no persona rows, or only retired ones, the General row is
  the score.
- A persona with no weight among others that have one gets the mean of the
  set weights (neutral), so it neither dominates nor vanishes; if none has a
  weight, all are equal.
- A retired persona (`ScoringTarget.is_active` false) stays visible but is
  skipped by the roll-up and the Blocker flag. A target the provider no
  longer lists (persona deleted/hidden, or the Stakeholders module off) is `unavailable`:
  it still counts, unweighted and unlabelled, and the summary reports
  `personas_degraded` so the UI/reports can say so.
- The Blocker flag keys off the top Severity level on any counted score row,
  independent of the model and roll-up, so it can't be averaged away.
- A level stored on a criterion that has since been hidden is kept on save and
  ignored by the maths.
- Scoring is a manager-tier action (the router enforces it): Pain Point
  creation is broad, but prioritisation isn't.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
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
from app.modules.context_strategy.models import PainPoint, PainPointScore, PainPointScoreAxis
from app.modules.context_strategy.scoring import PAIN_POINT_SCORING_SCHEME_KEY
from app.modules.registry import (
    ScoringAxisDefinition,
    ScoringModelDefinition,
    ScoringSchemeDefinition,
    ScoringTarget,
    get_scoring_targets,
)
from app.services.audit import log_event
from app.services.scoring import (
    BandValue,
    CellRatings,
    ScoreResult,
    band_for,
    compute_score,
    get_registered_scheme,
    list_levels,
    max_axis_weights,
    min_axis_weights,
    resolve_effective_bands,
    resolve_effective_cell_ratings,
    resolve_effective_model,
    to_cell_ratings,
)
from app.services.scoring_custom import effective_scheme

PERSONA_TARGET_TYPE = "persona"
SEVERITY_AXIS = "severity"


class RollupMethod(str, Enum):
    """How per-persona scores combine into one."""

    WEIGHTED_AVERAGE = "weighted_average"
    WORST_CASE = "worst_case"
    AVERAGE = "average"


class TargetStatus(str, Enum):
    """How a score row's target resolves right now."""

    GENERAL = "general"  # the General row
    ACTIVE = "active"
    INACTIVE = "inactive"  # listed but retired: shown, not counted
    UNAVAILABLE = "unavailable"  # no longer listed: counted unweighted


@dataclass(frozen=True)
class ScoreEntryInput:
    """One requested row of a Pain Point's score set.

    Attributes:
        target_id: The persona scored for, or `None` for the General row.
        levels: Chosen level id by axis key; `None` or a missing axis = not
            scored on that axis.
    """

    target_id: uuid.UUID | None
    levels: Mapping[str, uuid.UUID | None] = field(default_factory=dict)


@dataclass
class ScoringContext:
    """Everything needed to score the Pain Points of one project.

    Attributes:
        project: The project.
        scheme: The `pain_point` scheme as it applies to the project (the
            registered criteria plus the organisation's and projects' own,
            minus the hidden ones).
        levels_by_id: The org's levels for the scheme, by id.
        levels_by_axis: Those levels by axis key, lowest weight first.
        max_weights / min_weights: Each axis's top and lowest level weight.
        top_severity_weight: The highest Severity weight (the Blocker level).
        per_target_axes: Keys of the axes scored per persona.
        default_model_key / default_model_source: The project's resolved
            default model and where it came from.
        targets: The project's persona scoring targets by id (empty when
            the Stakeholders & Personas module or its persona sub-component is off).
    """

    project: Project
    scheme: ScoringSchemeDefinition
    levels_by_id: dict[uuid.UUID, ScoringLevel]
    levels_by_axis: dict[str, list[ScoringLevel]]
    max_weights: dict[str, Decimal]
    min_weights: dict[str, Decimal]
    top_severity_weight: Decimal | None
    per_target_axes: frozenset[str]
    default_model_key: str
    default_model_source: str
    targets: dict[uuid.UUID, ScoringTarget]


@dataclass
class EntrySummary:
    """One score row, resolved.

    Attributes:
        row: The stored row.
        label: The target's name, or `None` (General / unavailable).
        weight: The target's persona weight, or `None`.
        target_status: See `TargetStatus`.
        levels: The levels the row itself holds, by axis key.
        effective_levels: The levels the row scores with: its own, with the
            General row's filling every criterion a persona row does not
            override.
        score: The row's score under the chosen model, or `None` (not scored
            under this model).
        is_blocker: Whether Severity is the top level on this row.
    """

    row: PainPointScore
    label: str | None
    weight: float | None
    target_status: TargetStatus
    levels: dict[str, uuid.UUID]
    effective_levels: dict[str, uuid.UUID]
    score: ScoreResult | None
    is_blocker: bool


@dataclass
class PainPointScoringSummary:
    """A Pain Point's roll-up under one model and method.

    Attributes:
        pain_point_id: The Pain Point.
        scope: `"none"` (no rows), `"general"` (the General row only) or
            `"per_persona"` (at least one persona row).
        entries: Resolved rows.
        score: The rolled-up score, or `None` if nothing is scored under the
            model.
        counted: Rows that fed the roll-up.
        is_blocker: Any counted row is at the top Severity level.
        blocker_labels: Names of the blocked personas (empty for a General
            blocker or unlabelled targets).
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


# --- Reading and writing one row's levels -------------------------------------


def score_level_ids(row: PainPointScore) -> dict[str, uuid.UUID]:
    """The levels a stored score row holds, by axis key.

    This is the one place that knows how a row stores its levels; every
    reader (roll-up, matrix, export, API output, grid) goes through it.

    Args:
        row: A stored score row.

    Returns:
        The chosen level id of each axis the row is scored on; an axis the
        row is not scored on is absent.
    """
    return {axis.axis_key: axis.level_id for axis in row.axes}


def entry_level_ids(entry: ScoreEntryInput) -> dict[str, uuid.UUID]:
    """The levels a requested score row holds, by axis key (see `score_level_ids`); unscored axes are absent."""
    return {axis_key: level_id for axis_key, level_id in entry.levels.items() if level_id is not None}


def assign_score_level_ids(row: PainPointScore, levels: Mapping[str, uuid.UUID | None]) -> bool:
    """Sets a stored score row's levels from `levels`.

    Args:
        row: The row to change.
        levels: Axis key to level id. The row ends up scored on exactly the
            axes given a level: pass the complete set, `None` or a missing
            axis clears it.

    Returns:
        Whether any level changed.
    """
    wanted = {axis_key: level_id for axis_key, level_id in levels.items() if level_id is not None}
    current = {axis.axis_key: axis for axis in row.axes}
    changed = False
    for axis_key, held in current.items():
        if axis_key not in wanted:
            row.axes.remove(held)
            changed = True
    for axis_key, level_id in wanted.items():
        stored = current.get(axis_key)
        if stored is None:
            row.axes.append(PainPointScoreAxis(axis_key=axis_key, level_id=level_id))
            changed = True
        elif stored.level_id != level_id:
            stored.level_id = level_id
            changed = True
    return changed


def offered_level_ids(ctx: ScoringContext, row: PainPointScore) -> dict[str, uuid.UUID]:
    """The levels a stored row holds on criteria the project currently offers (a hidden criterion's level is
    kept by `set_pain_point_scores` itself, so a caller re-submitting a row leaves it out)."""
    return {key: level for key, level in score_level_ids(row).items() if ctx.scheme.axis(key) is not None}


def general_row(rows: list[PainPointScore]) -> PainPointScore | None:
    """The General row (no target) of a Pain Point's score rows, or `None`."""
    return next((row for row in rows if row.target_id is None), None)


# --- Context -----------------------------------------------------------------


def load_scoring_context(db: Session, project: Project) -> ScoringContext:
    """Loads the effective scheme, org levels, default model and persona targets for
    scoring in `project`.

    Raises:
        HTTPException: 404 if no module registers the `pain_point` scheme.
    """
    registered = get_registered_scheme(PAIN_POINT_SCORING_SCHEME_KEY)
    scheme = effective_scheme(db, project.organization_id, registered.scheme, project.id)
    levels_by_axis = list_levels(db, project.organization_id, scheme.key)
    default_model_key, default_source = resolve_effective_model(db, project.organization_id, scheme, project.id)
    max_weights = max_axis_weights(levels_by_axis)
    return ScoringContext(
        project=project, scheme=scheme,
        levels_by_id={lvl.id: lvl for levels in levels_by_axis.values() for lvl in levels},
        levels_by_axis=levels_by_axis, max_weights=max_weights, min_weights=min_axis_weights(levels_by_axis),
        top_severity_weight=max_weights.get(SEVERITY_AXIS),
        per_target_axes=frozenset(axis.key for axis in scheme.axes if axis.per_target),
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
    """Returns a Pain Point's stored score rows (the General row first)."""
    return list(db.scalars(
        select(PainPointScore).where(PainPointScore.pain_point_id == pain_point_id)
        .order_by(PainPointScore.target_id.is_(None).desc(), PainPointScore.created_at)
    ).all())


def _validate_level(ctx: ScoringContext, axis_key: str, level_id: uuid.UUID) -> ScoringAxisDefinition:
    """Returns the criterion `axis_key`, after checking `level_id` is one of its levels.

    Raises:
        HTTPException: 400 for a criterion this project does not offer, or a level that is not its level.
    """
    axis = ctx.scheme.axis(axis_key)
    if axis is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown scoring criterion '{axis_key}'.")
    level = ctx.levels_by_id.get(level_id)
    if level is None or level.axis_key != axis_key:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Invalid {axis_key} level.")
    return axis


def set_pain_point_scores(
    db: Session, ctx: ScoringContext, pain_point: PainPoint, entries: list[ScoreEntryInput], actor: User,
) -> list[PainPointScore]:
    """Replaces a Pain Point's score set with `entries` (flushed, not
    committed) and audit-logs the change if anything changed.

    Entries with no level chosen are dropped. At most one row per target. The
    General row (`target_id` None) may hold any criterion; a persona row only
    the criteria scored per persona. A persona must be one of the project's
    current scoring targets, and a retired one can only be kept if it already
    has a row. Levels stored on a criterion the project no longer offers
    (hidden) are kept.

    Raises:
        HTTPException: 400 for a duplicate target, a whole-Pain-Point criterion
            on a persona row, an unknown/inactive persona, an unknown
            criterion, or a level that isn't this org's level for that axis;
            409 if a concurrent save or level deletion collides with this one.
    """
    kept = [e for e in entries if entry_level_ids(e)]
    target_ids = [e.target_id for e in kept]
    if len(set(target_ids)) != len(target_ids):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Each persona can be scored once.")
    existing = {row.target_id: row for row in list_pain_point_scores(db, pain_point.id)}
    for entry in kept:
        for axis_key, level_id in entry_level_ids(entry).items():
            axis = _validate_level(ctx, axis_key, level_id)
            if entry.target_id is not None and not axis.per_target:
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    f"'{axis.label}' is scored for the whole Pain Point; set it on the General row.",
                )
        if entry.target_id is not None:
            target = ctx.targets.get(entry.target_id)
            if target is None:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "That persona isn't available to score in this project.")
            if not target.is_active and entry.target_id not in existing:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "A retired persona can't be newly scored.")

    offered = {axis.key for axis in ctx.scheme.axes}
    changed = False
    wanted = {e.target_id: e for e in kept}
    for target_id, row in existing.items():
        if target_id not in wanted:
            db.delete(row)
            changed = True
    for target_id, entry in wanted.items():
        current = existing.get(target_id)
        levels = entry_level_ids(entry)
        if current is None:
            row = PainPointScore(
                pain_point_id=pain_point.id, target_type=PERSONA_TARGET_TYPE if target_id else None,
                target_id=target_id, scored_by=actor.id,
            )
            assign_score_level_ids(row, levels)
            db.add(row)
            changed = True
            continue
        hidden = {key: level for key, level in score_level_ids(current).items() if key not in offered}
        if assign_score_level_ids(current, {**levels, **hidden}):
            current.scored_by = actor.id
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
            detail={"general": None in wanted, "scored_targets": len([t for t in wanted if t is not None])},
        )
    return list_pain_point_scores(db, pain_point.id)


# --- Maths -------------------------------------------------------------------


def _levels_weights(ctx: ScoringContext, levels: Mapping[str, uuid.UUID]) -> dict[str, Decimal | None]:
    """Maps each criterion of the scheme to the weight of the chosen level (`None` = unscored); a level stored on
    a criterion the scheme no longer offers is ignored."""
    out: dict[str, Decimal | None] = {}
    for axis in ctx.scheme.axes:
        level_id = levels.get(axis.key)
        level = ctx.levels_by_id.get(level_id) if level_id is not None else None
        out[axis.key] = level.weight if level is not None else None
    return out


def _effective_levels(ctx: ScoringContext, row: PainPointScore, general: PainPointScore | None) -> dict[str, uuid.UUID]:
    """The levels a row scores with: a persona row's own per-persona criteria over the General row's levels;
    the General row's own levels otherwise."""
    own = score_level_ids(row)
    if row.target_id is None or general is None:
        return own
    return {**score_level_ids(general), **{key: level for key, level in own.items() if key in ctx.per_target_axes}}


def _resolve_entry(
    ctx: ScoringContext, row: PainPointScore, general: PainPointScore | None, model: ScoringModelDefinition,
    bands: list[BandValue], cells: CellRatings | None = None,
) -> EntrySummary:
    """Resolves one stored row against its target, the General row and the chosen model
    (`cells`: the model's per-cell rating overrides, if any)."""
    effective = _effective_levels(ctx, row, general)
    weights = _levels_weights(ctx, effective)
    severity = weights.get(SEVERITY_AXIS)
    is_blocker = severity is not None and ctx.top_severity_weight is not None and severity == ctx.top_severity_weight
    score = compute_score(
        model, weights, ctx.max_weights, bands, level_ids=effective, cell_ratings=cells, min_weights=ctx.min_weights,
    )
    own = score_level_ids(row)
    if row.target_id is None:
        return EntrySummary(row, None, None, TargetStatus.GENERAL, own, effective, score, is_blocker)
    target = ctx.targets.get(row.target_id)
    if target is None:
        return EntrySummary(row, None, None, TargetStatus.UNAVAILABLE, own, effective, score, is_blocker)
    state = TargetStatus.ACTIVE if target.is_active else TargetStatus.INACTIVE
    return EntrySummary(row, target.label, target.weight, state, own, effective, score, is_blocker)


def _mean_weight_fill(entries: list[EntrySummary]) -> list[Decimal]:
    """Returns each entry's roll-up weight: its own, else the mean of the set
    weights, else 1 for everyone."""
    set_weights = [Decimal(str(e.weight)) for e in entries if e.weight is not None]
    fill = sum(set_weights, Decimal(0)) / len(set_weights) if set_weights else Decimal(1)
    return [Decimal(str(e.weight)) if e.weight is not None else fill for e in entries]


def rollup_scores(
    entries: list[EntrySummary], method: RollupMethod, bands: list[BandValue],
) -> ScoreResult | None:
    """Combines the scored entries under `method`, or `None` if none is scored.

    A single scored entry is returned as is, so its explicit cell rating (if
    any) survives; a blend of several entries is not one cell, so it takes
    the threshold bands."""
    scored = [(e, e.score) for e in entries if e.score is not None]
    if not scored:
        return None
    if len(scored) == 1:
        return scored[0][1]
    if method is RollupMethod.WORST_CASE:
        return max(scored, key=lambda pair: pair[1].normalised)[1]
    if method is RollupMethod.AVERAGE:
        weights = [Decimal(1)] * len(scored)
    else:
        weights = _mean_weight_fill([e for e, _ in scored])
    total = sum(weights)
    pairs = list(zip(weights, (score for _, score in scored), strict=True))
    raw = sum((w * score.raw for w, score in pairs), Decimal(0)) / total
    normalised = float(sum((w * Decimal(str(score.normalised)) for w, score in pairs), Decimal(0)) / total)
    return ScoreResult(raw=raw, normalised=normalised, band=band_for(normalised, bands))


def summarise(
    ctx: ScoringContext, pain_point_id: uuid.UUID, rows: list[PainPointScore], model: ScoringModelDefinition,
    method: RollupMethod, bands: list[BandValue], cells: CellRatings | None = None,
) -> PainPointScoringSummary:
    """Rolls a Pain Point's rows up under `model` and `method`.

    The persona rows that are not retired are what counts; with none, the
    General row is the score."""
    summary = PainPointScoringSummary(pain_point_id=pain_point_id, scope="none")
    if not rows:
        return summary
    general = general_row(rows)
    summary.entries = [_resolve_entry(ctx, row, general, model, bands, cells) for row in rows]
    personas = [e for e in summary.entries if e.target_status is not TargetStatus.GENERAL]
    summary.scope = "per_persona" if personas else "general"
    counted = [e for e in personas if e.target_status is not TargetStatus.INACTIVE]
    if not counted:
        counted = [e for e in summary.entries if e.target_status is TargetStatus.GENERAL]
    summary.counted = len(counted)
    summary.personas_degraded = any(e.target_status is TargetStatus.UNAVAILABLE for e in summary.entries)
    summary.score = rollup_scores(counted, method, bands)
    blockers = [e for e in counted if e.is_blocker]
    summary.is_blocker = bool(blockers)
    summary.blocker_labels = sorted(e.label for e in blockers if e.label)
    return summary


def build_pain_point_scoring(
    db: Session, ctx: ScoringContext, pain_points: list[PainPoint], model: ScoringModelDefinition,
    method: RollupMethod,
) -> list[PainPointScoringSummary]:
    """Summarises many Pain Points of one project in a single pass (one
    query for all score rows, one more for their levels).

    Returns:
        One summary per Pain Point, in input order.
    """
    bands, _ = resolve_effective_bands(db, ctx.project.organization_id, ctx.scheme, model.key, ctx.project.id)
    cells = to_cell_ratings(
        resolve_effective_cell_ratings(db, ctx.project.organization_id, ctx.scheme, model.key, ctx.project.id)[0]
    )
    rows_by_pp: dict[uuid.UUID, list[PainPointScore]] = {}
    if pain_points:
        for row in db.scalars(
            select(PainPointScore).where(PainPointScore.pain_point_id.in_([p.id for p in pain_points]))
            .order_by(PainPointScore.target_id.is_(None).desc(), PainPointScore.created_at)
        ).all():
            rows_by_pp.setdefault(row.pain_point_id, []).append(row)
    return [summarise(ctx, p.id, rows_by_pp.get(p.id, []), model, method, bands, cells) for p in pain_points]
