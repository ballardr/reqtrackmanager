"""
Module: modules.risk_management.ratings

Derives a Risk's inherent and residual rating from its scoring levels, using
core's scoring service so the project's effective default model, rating bands
and per-cell overrides (project -> nearest ancestor -> org -> registry default)
all apply with no Risk-specific matrix code.

A rating is derived on every read, never stored: re-weighting a level or editing
a band or cell rating therefore re-rates every risk immediately. One
`RatingContext` is loaded per request and reused for every risk in it, so a
register listing costs a fixed number of queries.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models.project import Project
from app.models.scoring import ScoringLevel
from app.modules.registry import ScoringModelDefinition
from app.modules.risk_management.models import RiskVersion
from app.modules.risk_management.scoring import (
    CONSEQUENCE_AXIS_KEY,
    DETECTABILITY_AXIS_KEY,
    LIKELIHOOD_AXIS_KEY,
    RISK_SCORING_SCHEME_KEY,
)
from app.services.scoring import (
    BandValue,
    CellRatings,
    compute_score,
    get_registered_scheme,
    list_levels,
    max_axis_weights,
    resolve_effective_bands,
    resolve_effective_cell_ratings,
    resolve_effective_model,
    to_cell_ratings,
)


@dataclass(frozen=True)
class RiskRating:
    """A derived rating.

    Attributes:
        scoring_model_key: The scoring model it was computed under.
        raw: Product of the chosen level weights.
        normalised: `raw` divided by the model's maximum possible score, in (0, 1].
        label: The matching band's label (a per-cell override wins over thresholds).
        tone: The matching band's tone, or `None` with no bands.
    """

    scoring_model_key: str
    raw: float
    normalised: float
    label: str | None
    tone: str | None


@dataclass(frozen=True)
class RatingContext:
    """Everything needed to rate any number of risks of one project.

    Attributes:
        model: The project's effective default scoring model.
        levels_by_id: Every level of the `risk` scheme in the organisation.
        max_weights: Each axis's top level weight.
        bands: The model's effective rating bands.
        cells: The model's effective per-cell rating overrides.
    """

    model: ScoringModelDefinition
    levels_by_id: Mapping[uuid.UUID, ScoringLevel]
    max_weights: Mapping[str, Decimal]
    bands: list[BandValue]
    cells: CellRatings


def load_rating_context(db: Session, project: Project) -> RatingContext:
    """Loads the scheme configuration effective for `project`.

    Raises:
        HTTPException: 404 if no module registers the `risk` scheme.
    """
    scheme = get_registered_scheme(RISK_SCORING_SCHEME_KEY).scheme
    levels_by_axis = list_levels(db, project.organization_id, scheme.key)
    model_key, _ = resolve_effective_model(db, project.organization_id, scheme, project.id)
    model = scheme.model(model_key)
    assert model is not None  # resolve_effective_model only returns keys the scheme defines
    bands, _ = resolve_effective_bands(db, project.organization_id, scheme, model_key, project.id)
    cells = to_cell_ratings(resolve_effective_cell_ratings(db, project.organization_id, scheme, model_key, project.id)[0])
    return RatingContext(
        model=model,
        levels_by_id={level.id: level for levels in levels_by_axis.values() for level in levels},
        max_weights=max_axis_weights(levels_by_axis),
        bands=bands,
        cells=cells,
    )


def rate_levels(
    ctx: RatingContext, *, likelihood: uuid.UUID | None, consequence: uuid.UUID | None, detectability: uuid.UUID | None
) -> RiskRating | None:
    """Rates one set of level ids under the context's model.

    Returns:
        The rating, or `None` ("not scored") when any axis the model needs has
        no level, e.g. Detectability is missing under the three-axis model.
    """
    level_ids = {LIKELIHOOD_AXIS_KEY: likelihood, CONSEQUENCE_AXIS_KEY: consequence, DETECTABILITY_AXIS_KEY: detectability}
    weights = {
        axis: ctx.levels_by_id[level_id].weight if level_id in ctx.levels_by_id else None for axis, level_id in level_ids.items()
    }
    result = compute_score(ctx.model, weights, ctx.max_weights, ctx.bands, level_ids=level_ids, cell_ratings=ctx.cells)
    if result is None:
        return None
    return RiskRating(
        scoring_model_key=ctx.model.key, raw=float(result.raw), normalised=result.normalised,
        label=result.band.label if result.band else None, tone=result.band.tone if result.band else None,
    )


def rate_version(ctx: RatingContext, version: RiskVersion) -> tuple[RiskRating | None, RiskRating | None]:
    """The `(inherent, residual)` ratings of a risk version."""
    inherent = rate_levels(
        ctx, likelihood=version.inherent_likelihood_level_id, consequence=version.inherent_consequence_level_id,
        detectability=version.inherent_detectability_level_id,
    )
    residual = rate_levels(
        ctx, likelihood=version.residual_likelihood_level_id, consequence=version.residual_consequence_level_id,
        detectability=version.residual_detectability_level_id,
    )
    return inherent, residual
