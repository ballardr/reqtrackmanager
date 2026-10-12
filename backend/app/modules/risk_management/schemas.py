"""
Module: modules.risk_management.schemas

Pydantic request/response schemas for the Risk Management module's project
router: Risk create/update/out, version history, derived ratings and comments.
Type-vocabulary schemas are the shared ones in `app.schemas.type_vocabulary`.

`RiskUpdate` is partial: only fields present in the request body change, so a
nullable field (type, strategy, any level, owner, review date) can be cleared
by sending an explicit `null`. `status` is not editable here (the lifecycle
transition endpoint owns it).
"""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.modules.risk_management.enums import RiskStatus, TreatmentAssessmentStatus, TreatmentStrategy
from app.schemas.file import FileAssetOut


class RiskCreate(BaseModel):
    """Create payload; only `title` is required. `status` is not accepted (a risk starts `IDENTIFIED`)."""
    title: str = Field(min_length=1, max_length=300)
    statement: str = ""
    cause: str = ""
    risk_event: str = ""
    consequence: str = ""
    risk_type_id: UUID | None = None
    treatment_strategy: TreatmentStrategy | None = None
    acceptance_criteria: str = ""
    inherent_likelihood_level_id: UUID | None = None
    inherent_consequence_level_id: UUID | None = None
    inherent_detectability_level_id: UUID | None = None
    residual_likelihood_level_id: UUID | None = None
    residual_consequence_level_id: UUID | None = None
    residual_detectability_level_id: UUID | None = None
    owner_id: UUID | None = None
    review_date: date | None = None


class RiskUpdate(BaseModel):
    """Partial update; see module docstring."""

    title: str | None = Field(default=None, min_length=1, max_length=300)
    statement: str | None = None
    cause: str | None = None
    risk_event: str | None = None
    consequence: str | None = None
    risk_type_id: UUID | None = None
    treatment_strategy: TreatmentStrategy | None = None
    acceptance_criteria: str | None = None
    inherent_likelihood_level_id: UUID | None = None
    inherent_consequence_level_id: UUID | None = None
    inherent_detectability_level_id: UUID | None = None
    residual_likelihood_level_id: UUID | None = None
    residual_consequence_level_id: UUID | None = None
    residual_detectability_level_id: UUID | None = None
    owner_id: UUID | None = None
    review_date: date | None = None
    change_note: str = ""


class RiskTransitionRequest(BaseModel):
    """A lifecycle move. `comment` is recorded as the new version's change note
    and in the audit event."""

    status: RiskStatus
    comment: str = ""


class RiskRatingOut(BaseModel):
    """A derived rating (never stored). `label`/`tone` are the effective band
    (or per-cell override); `normalised` is the score on a 0-1 scale."""

    scoring_model_key: str
    raw: float
    normalised: float
    label: str | None
    tone: str | None


class RiskOut(BaseModel):
    """A risk merged with its current version and derived ratings."""

    id: UUID
    project_id: UUID
    unique_code: str
    creator_id: UUID
    is_archived: bool
    archived_at: datetime | None
    archived_by: UUID | None

    title: str
    statement: str
    cause: str
    risk_event: str
    consequence: str
    risk_type_id: UUID | None
    risk_type_name: str | None
    treatment_strategy: TreatmentStrategy | None
    acceptance_criteria: str
    inherent_likelihood_level_id: UUID | None
    inherent_consequence_level_id: UUID | None
    inherent_detectability_level_id: UUID | None
    residual_likelihood_level_id: UUID | None
    residual_consequence_level_id: UUID | None
    residual_detectability_level_id: UUID | None
    inherent_rating: RiskRatingOut | None
    residual_rating: RiskRatingOut | None
    status: RiskStatus
    allowed_next_statuses: list[RiskStatus]
    owner_id: UUID | None
    review_date: date | None
    version_number: int
    effective_treatment_count: int = 0
    is_effectively_treated: bool = False

    created_at: datetime
    updated_at: datetime


class RiskVersionOut(BaseModel):
    """One historical snapshot."""

    model_config = {"from_attributes": True}

    id: UUID
    risk_id: UUID
    version_number: int
    valid_from: datetime
    valid_to: datetime | None
    title: str
    statement: str
    cause: str
    risk_event: str
    consequence: str
    project_type_id: UUID | None
    treatment_strategy: TreatmentStrategy | None
    acceptance_criteria: str
    inherent_likelihood_level_id: UUID | None
    inherent_consequence_level_id: UUID | None
    inherent_detectability_level_id: UUID | None
    residual_likelihood_level_id: UUID | None
    residual_consequence_level_id: UUID | None
    residual_detectability_level_id: UUID | None
    status: RiskStatus
    owner_id: UUID | None
    review_date: date | None
    change_note: str
    created_by: UUID
    created_at: datetime


class RiskCommentCreate(BaseModel):
    """A new comment."""
    body: str = Field(min_length=1)


class RiskCommentUpdate(BaseModel):
    """A comment's replacement text."""
    body: str = Field(min_length=1)


class RiskCommentOut(BaseModel):
    """A comment with its author's display name and attachments."""
    id: UUID
    risk_id: UUID
    author_id: UUID
    author_display_name: str
    body: str
    created_at: datetime
    edited_at: datetime | None = None
    attachments: list[FileAssetOut] = []


class TreatmentAssessmentRequest(BaseModel):
    """A verdict on one treatment link. A rationale is required for `effective`
    and `ineffective`."""
    status: TreatmentAssessmentStatus
    rationale: str = ""


class TreatmentOut(BaseModel):
    """One treatment link of a risk with its far end and verdict. `status` is
    `proposed` when nobody has assessed the link yet."""
    link_id: UUID
    relationship: str
    other_type: str
    other_type_label: str
    other_id: UUID
    other_project_id: UUID | None
    label: str
    other_status: str | None
    other_is_archived: bool
    status: TreatmentAssessmentStatus
    rationale: str
    assessed_by: UUID | None
    assessed_at: datetime | None


class TreatmentListOut(BaseModel):
    """A risk's visible treatment links; `hidden_count` links point at records the caller cannot see."""
    items: list[TreatmentOut]
    hidden_count: int
    effective_count: int
