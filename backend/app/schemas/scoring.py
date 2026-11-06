"""
Module: schemas.scoring

Request/response models for the generic scoring-matrix API: a scheme's effective configuration (axes with levels, models
with bands, default model with its resolution source), level CRUD, and the
default-model/band/cell-rating override payloads. See `services.scoring`.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

ResolutionSource = Literal["project", "ancestor", "org", "system", "none"]


class ScoringLevelOut(BaseModel):
    """One level of an axis (ascending weight order)."""

    id: UUID
    name: str
    description: str | None
    weight: float
    threshold: float | None = None
    org_threshold: float | None = Field(
        default=None, description="A derived axis's organisation threshold; `threshold` is the one in force for the caller's project.",
    )


class ScoringAxisOut(BaseModel):
    """An axis with the organisation's levels."""

    key: str
    label: str
    description: str | None
    derived_source: str | None = None
    origin: Literal["built_in", "org", "project"] = "built_in"
    owner_project_id: UUID | None = None
    thresholds_source: Literal["project", "ancestor", "organisation"] | None = Field(
        default=None, description="Where a derived axis's thresholds in force come from; `None` on an ordinary axis.",
    )
    levels: list[ScoringLevelOut]


class ScoringBandIn(BaseModel):
    """One rating band in a band-set payload."""

    label: str = Field(min_length=1, max_length=100)
    min_score: float = Field(ge=0, lt=1)
    tone: str


class ScoringBandOut(BaseModel):
    """One resolved rating band."""

    label: str
    min_score: float
    tone: str


class ScoringCellRatingIn(BaseModel):
    """One cell of a cell-rating payload: the band the (first-axis level,
    second-axis level) cell is rated as."""

    first_level_id: UUID
    second_level_id: UUID
    band_label: str = Field(min_length=1, max_length=100)


class ScoringCellRatingOut(ScoringCellRatingIn):
    """One resolved cell rating."""


class ScoringModelOut(BaseModel):
    """A model with its effective bands, cell ratings and where each came
    from. `cell_ratings` is always empty for a model that isn't two-axis."""

    key: str
    label: str
    axis_keys: list[str]
    divisor_axis_keys: list[str] = []
    combination: Literal["product", "weighted_sum"] = "product"
    exponents: dict[str, float] = {}
    importance: dict[str, float] = {}
    inverted_axis_keys: list[str] = []
    origin: Literal["built_in", "org", "project"] = "built_in"
    owner_project_id: UUID | None = None
    bands: list[ScoringBandOut]
    bands_source: ResolutionSource
    cell_ratings: list[ScoringCellRatingOut]
    cell_ratings_source: ResolutionSource


class HiddenCriterionOut(BaseModel):
    """A registered or inherited axis or model this tier hid, which it can restore."""

    kind: Literal["axis", "model"]
    key: str
    label: str


class ScoringSchemeOut(BaseModel):
    """A scheme's effective configuration for an org or a project."""

    key: str
    label: str
    module_key: str
    axes: list[ScoringAxisOut]
    models: list[ScoringModelOut]
    system_default_model_key: str
    default_model_key: str
    default_model_source: ResolutionSource
    enabled_model_keys: list[str] = []
    enabled_models_source: ResolutionSource = "system"
    allow_custom_criteria: bool = False
    side_by_side_models: bool = False
    hidden_criteria: list[HiddenCriterionOut] = []


class ScoringLevelCreate(BaseModel):
    """Payload to add a level to an axis."""

    name: str = Field(min_length=1, max_length=100)
    weight: float = Field(gt=0, le=1_000_000)
    description: str | None = Field(default=None, max_length=2000)
    threshold: float | None = Field(default=None, ge=0, le=1_000_000_000)


class ScoringLevelUpdate(BaseModel):
    """Partial level update; omitted fields are unchanged. Send
    `description: null` explicitly to clear the description."""

    name: str | None = Field(default=None, min_length=1, max_length=100)
    weight: float | None = Field(default=None, gt=0, le=1_000_000)
    description: str | None = Field(default=None, max_length=2000)
    threshold: float | None = Field(default=None, ge=0, le=1_000_000_000)


class ScoringDefaultModelIn(BaseModel):
    """Sets the default model (by model key); `null` clears the override so
    it inherits. Named `model`, not `model_key`, because pydantic reserves
    the `model_` prefix."""

    model: str | None


class ScoringEnabledModelsIn(BaseModel):
    """Replaces the set of enabled models (by model key); `null` clears the override so it inherits."""

    models: list[str] | None


class ScoringThresholdsIn(BaseModel):
    """Replaces a project's thresholds for a derived axis: a threshold for every level (by level id), rising with the
    levels' weights; `null` clears the override so it inherits."""

    thresholds: dict[UUID, float] | None


class ScoringBandsIn(BaseModel):
    """Replaces a band set; `null` clears the override so it inherits."""

    bands: list[ScoringBandIn] | None


class ScoringCellRatingsIn(BaseModel):
    """Replaces a model's cell-rating set; `null` (or an empty list) clears
    the override so it inherits."""

    cells: list[ScoringCellRatingIn] | None


class ScoringLevelSpecIn(BaseModel):
    """One level of a new axis."""

    name: str = Field(min_length=1, max_length=100)
    weight: float = Field(gt=0, le=1_000_000)
    description: str | None = Field(default=None, max_length=2000)


class ScoringAxisCreate(BaseModel):
    """Defines an axis (name, optional guidance and its first levels)."""

    label: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=2000)
    levels: list[ScoringLevelSpecIn] = Field(min_length=2, max_length=12)


class ScoringAxisUpdate(BaseModel):
    """Renames or re-describes an axis; send `description: null` to clear it."""

    label: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=2000)


class ScoringModelAxisIn(BaseModel):
    """How a model uses one axis: `multiply` or `divide` (with an `exponent`) in a product, `sum` (with an
    `importance` percentage and optionally `lower_is_better`) in a weighted sum."""

    axis_key: str = Field(min_length=1, max_length=64)
    role: Literal["multiply", "divide", "sum"]
    exponent: float = Field(default=1.0, gt=0, le=10)
    importance: float | None = Field(default=None, gt=0, le=100)
    lower_is_better: bool = False


class ScoringModelCreate(BaseModel):
    """Defines a model: a name, how it combines its axes and which axes it uses."""

    label: str = Field(min_length=1, max_length=100)
    combination: Literal["product", "weighted_sum"]
    axes: list[ScoringModelAxisIn] = Field(min_length=1, max_length=20)


class ScoringModelUpdate(BaseModel):
    """Renames a model and/or replaces its axes (and, optionally, its combination)."""

    label: str | None = Field(default=None, min_length=1, max_length=100)
    combination: Literal["product", "weighted_sum"] | None = None
    axes: list[ScoringModelAxisIn] | None = Field(default=None, min_length=1, max_length=20)


class ScoringCriterionRef(BaseModel):
    """Names a criterion to hide or restore."""

    kind: Literal["axis", "model"]
    key: str = Field(min_length=1, max_length=64)
