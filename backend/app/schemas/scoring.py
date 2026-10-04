"""
Module: schemas.scoring

Request/response models for the generic scoring-matrix API (Module 1
Phase 10): a scheme's effective configuration (axes with levels, models
with bands, default model with its resolution source), level CRUD, and the
default-model/band override payloads. See `services.scoring`.
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


class ScoringAxisOut(BaseModel):
    """An axis with the organisation's levels."""

    key: str
    label: str
    description: str | None
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


class ScoringModelOut(BaseModel):
    """A model with its effective bands and where they came from."""

    key: str
    label: str
    axis_keys: list[str]
    bands: list[ScoringBandOut]
    bands_source: ResolutionSource


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


class ScoringLevelCreate(BaseModel):
    """Payload to add a level to an axis."""

    name: str = Field(min_length=1, max_length=100)
    weight: float = Field(gt=0, le=1_000_000)
    description: str | None = Field(default=None, max_length=2000)


class ScoringLevelUpdate(BaseModel):
    """Partial level update; omitted fields are unchanged. Send
    `description: null` explicitly to clear the description."""

    name: str | None = Field(default=None, min_length=1, max_length=100)
    weight: float | None = Field(default=None, gt=0, le=1_000_000)
    description: str | None = Field(default=None, max_length=2000)


class ScoringDefaultModelIn(BaseModel):
    """Sets the default model (by model key); `null` clears the override so
    it inherits. Named `model`, not `model_key`, because pydantic reserves
    the `model_` prefix."""

    model: str | None


class ScoringBandsIn(BaseModel):
    """Replaces a band set; `null` clears the override so it inherits."""

    bands: list[ScoringBandIn] | None
