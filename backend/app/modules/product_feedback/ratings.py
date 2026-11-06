"""
Module: modules.product_feedback.ratings

Derives a request's scores from its scoring levels (one per axis) and its weighted demand, using core's scoring
service so the effective models, rating bands (project -> nearest ancestor -> organisation -> registry default)
and the level weights all apply with no request-specific maths.

A score is derived on every read, never stored: re-weighting a level or editing a band re-scores every request at
once, and several models are scored side by side from the same data (`scoring_model` picks them when viewing,
else the project's enabled models), so ICE and RICE can be compared without anything being written. One
`RatingContext` is loaded per project (or per organisation, for the inbox) and reused for every request in it, so
a list costs a fixed number of statements however many requests it holds.

The Demand axis is derived (`scoring.WEIGHTED_DEMAND_SOURCE`): with no level chosen manually it is the level the
request's weighted demand falls in, by the thresholds in force for its project (the organisation's, unless the project sets its own).

Dependencies: `services.scoring`, `scoring.py` (the scheme).
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.scoring import ScoringLevel
from app.modules.product_feedback.scoring import REQUEST_SCORING_SCHEME_KEY, WEIGHTED_DEMAND_SOURCE
from app.modules.registry import ScoringModelDefinition, ScoringSchemeDefinition
from app.services.scoring import (
    BandValue,
    compute_score,
    derived_level,
    effective_thresholds,
    get_registered_scheme,
    list_levels,
    max_axis_weights,
    min_axis_weights,
    resolve_effective_bands,
    resolve_enabled_models,
)
from app.services.scoring_custom import effective_scheme


@dataclass(frozen=True)
class RequestScore:
    """A derived score.

    Attributes:
        scoring_model_key: The model it was computed under.
        raw: The model's product of level weights, divided by its divisor axes' weights.
        normalised: `raw` divided by the model's best possible score, in (0, 1].
        label: The matching band's label, or `None` with no bands.
        tone: The matching band's tone, or `None` with no bands.
    """

    scoring_model_key: str
    raw: float
    normalised: float
    label: str | None
    tone: str | None


@dataclass(frozen=True)
class RatingContext:
    """Everything needed to score any number of requests of one project (or of the organisation's inbox).

    Attributes:
        scheme: The `enhancement_request` scheme as it applies here: registered axes and models plus the
            organisation's and project's own, minus what is hidden.
        models: The models scored, the primary (the one `RequestOut.score` shows) first.
        levels_by_axis: Every level of the scheme in the organisation, by axis, ascending weight.
        levels_by_id: The same levels by id.
        max_weights: Each axis's top level weight.
        min_weights: Each axis's lowest level weight.
        bands: Each model's effective rating bands, by model key.
        thresholds: `{level id: threshold}` in force for each derived axis's levels (the project's own, an
            ancestor's, or the organisation's).
    """

    scheme: ScoringSchemeDefinition
    models: list[ScoringModelDefinition]
    levels_by_axis: Mapping[str, list[ScoringLevel]]
    levels_by_id: Mapping[uuid.UUID, ScoringLevel]
    max_weights: Mapping[str, Decimal]
    min_weights: Mapping[str, Decimal]
    bands: Mapping[str, list[BandValue]]
    thresholds: Mapping[uuid.UUID, Decimal]

    @property
    def model(self) -> ScoringModelDefinition:
        """The primary model."""
        return self.models[0]


def parse_model_keys(values: Sequence[str] | None) -> list[str] | None:
    """The model keys a `scoring_model` query asked for: each value may itself be comma-separated; `None` when
    none was given (the caller then uses the enabled models)."""
    keys = [key.strip() for value in values or [] for key in value.split(",") if key.strip()]
    return list(dict.fromkeys(keys)) or None


def load_rating_context(
    db: Session, organization_id: uuid.UUID, project_id: uuid.UUID | None, model_keys: Sequence[str] | None = None,
) -> RatingContext:
    """Loads the scheme configuration effective for a project (or, with no `project_id`, the organisation).

    Args:
        db: Active session (read only).
        organization_id: The owning organisation.
        project_id: The project whose overrides apply, or `None` for the organisation's inbox.
        model_keys: The models to score under, primary first; `None` = the effective enabled models, with the
            default first.

    Raises:
        HTTPException: 404 if no module registers the scheme; 400 for a model the scheme does not define.
    """
    scheme = effective_scheme(db, organization_id, get_registered_scheme(REQUEST_SCORING_SCHEME_KEY).scheme, project_id)
    if not model_keys:
        model_keys, _ = resolve_enabled_models(db, organization_id, scheme, project_id)
    models = []
    for key in model_keys:
        model = scheme.model(key)
        if model is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown scoring model '{key}'.")
        models.append(model)
    levels_by_axis = list_levels(db, organization_id, scheme.key)
    return RatingContext(
        scheme=scheme, models=models, levels_by_axis=levels_by_axis,
        levels_by_id={level.id: level for levels in levels_by_axis.values() for level in levels},
        max_weights=max_axis_weights(levels_by_axis), min_weights=min_axis_weights(levels_by_axis),
        bands={model.key: resolve_effective_bands(db, organization_id, scheme, model.key, project_id)[0] for model in models},
        thresholds={
            level_id: value for axis in effective_thresholds(db, scheme, levels_by_axis, project_id).values()
            for level_id, value in axis.values.items()
        },
    )


def derived_levels(ctx: RatingContext, levels: Mapping[str, uuid.UUID], demand: float) -> dict[str, uuid.UUID]:
    """The levels the derived axes resolve to for a request, for each derived axis it has no level chosen manually
    on (a chosen level wins, so it is not listed here).

    Args:
        ctx: The scheme configuration.
        levels: The request's stored levels, axis key -> level id.
        demand: The request's weighted demand.
    """
    out: dict[str, uuid.UUID] = {}
    for axis in ctx.scheme.axes:
        if axis.derived_source != WEIGHTED_DEMAND_SOURCE or axis.key in levels:
            continue
        level = derived_level(ctx.levels_by_axis.get(axis.key, []), demand, ctx.thresholds)
        if level is not None:
            out[axis.key] = level.id
    return out


def score_levels(ctx: RatingContext, levels: Mapping[str, uuid.UUID], demand: float) -> dict[str, RequestScore | None]:
    """Scores one set of levels under every model of the context.

    Args:
        ctx: The scheme configuration.
        levels: The request's stored levels, axis key -> level id.
        demand: The request's weighted demand (what a derived axis is read from).

    Returns:
        `{model key: score}`; a score is `None` ("not scored") when an axis the model needs has no level, e.g.
        Reach is missing under RICE. A derived axis always has a level.
    """
    effective = {**derived_levels(ctx, levels, demand), **levels}
    weights = {}
    for axis in ctx.scheme.axes:
        level = ctx.levels_by_id.get(effective[axis.key]) if axis.key in effective else None
        weights[axis.key] = level.weight if level is not None else None
    scores: dict[str, RequestScore | None] = {}
    for model in ctx.models:
        result = compute_score(
            model, weights, ctx.max_weights, ctx.bands[model.key], min_weights=ctx.min_weights,
        )
        scores[model.key] = None if result is None else RequestScore(
            scoring_model_key=model.key, raw=float(result.raw), normalised=result.normalised,
            label=result.band.label if result.band else None, tone=result.band.tone if result.band else None,
        )
    return scores
