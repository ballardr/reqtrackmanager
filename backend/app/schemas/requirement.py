"""
Module: schemas.requirement

Request/response models for requirements, their version history, keywords,
traceability links, and discussion comments (C-G-02, C-G-09, C-M-01, C-R-01).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from app.models.enums import RequirementLevel, RequirementLinkType, RequirementReviewOutcome, RequirementStatus


class RequirementCreate(BaseModel):
    name: str
    reasoning: str = ""
    clarification: str = ""
    component_id: UUID
    category_id: UUID
    owner_id: UUID | None = None
    target_stage_id: UUID | None = None
    level: RequirementLevel = RequirementLevel.REQUIREMENT
    keywords: list[str] = []
    custom_fields: dict[str, Any] = {}
    creator_id: UUID | None = None  # PM-only override (C-A-11)
    review_date: date | None = None  # C-R-06
    review_lead_days: int | None = None  # C-R-08 per-requirement override
    reviewer_id: UUID | None = None  # C-R-10


class RequirementUpdate(BaseModel):
    """Direct edit payload. Rejected once the requirement is locked (C-G-12)."""

    name: str
    reasoning: str = ""
    clarification: str = ""
    component_id: UUID
    category_id: UUID
    owner_id: UUID
    status: RequirementStatus | None = None
    target_stage_id: UUID | None = None
    level: RequirementLevel = RequirementLevel.REQUIREMENT
    keywords: list[str] = []
    custom_fields: dict[str, Any] = {}
    change_note: str = ""
    review_date: date | None = None  # C-R-06 (blocked by is_locked() once approved, same as every other field here)
    review_lead_days: int | None = None
    reviewer_id: UUID | None = None


class RequirementOut(BaseModel):
    id: UUID
    project_id: UUID
    unique_code: str
    name: str
    reasoning: str
    clarification: str
    status: RequirementStatus
    owner_id: UUID
    component_id: UUID
    category_id: UUID
    target_stage_id: UUID | None = None
    level: RequirementLevel = RequirementLevel.REQUIREMENT
    sort_order: int
    creator_id: UUID
    is_archived: bool
    is_locked: bool
    keywords: list[str]
    custom_fields: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    is_subscribed: bool = False
    review_date: date | None = None
    review_lead_days: int | None = None
    reviewer_id: UUID | None = None
    # Derived list-view indicators (mock's card "badges") — not stored data,
    # computed at read time from comments/change-requests/status.
    comment_count: int = 0
    has_open_change_request: bool = False
    requires_approval: bool = False


class RequirementVersionOut(BaseModel):
    version_number: int
    name: str
    reasoning: str
    clarification: str
    status: RequirementStatus
    owner_id: UUID
    target_stage_id: UUID | None = None
    level: RequirementLevel = RequirementLevel.REQUIREMENT
    change_note: str
    change_request_id: UUID | None
    custom_fields: dict[str, Any]
    created_by: UUID
    created_at: datetime
    valid_to: datetime | None


class RequirementLinkCreate(BaseModel):
    target_requirement_id: UUID
    link_type: RequirementLinkType = RequirementLinkType.RELATES_TO


class RequirementLinkOut(BaseModel):
    id: UUID
    source_requirement_id: UUID
    target_requirement_id: UUID
    link_type: RequirementLinkType


class RequirementImportError(BaseModel):
    row: int
    message: str


class RequirementImportResult(BaseModel):
    created: int
    errors: list[RequirementImportError] = []


class CommentCreate(BaseModel):
    body: str


class CommentOut(BaseModel):
    id: UUID
    author_id: UUID
    author_display_name: str
    body: str
    created_at: datetime
    reaction_count: int = 0
    reacted_by_me: bool = False


class RequirementReviewCreate(BaseModel):
    outcome: RequirementReviewOutcome
    comment: str | None = None


class RequirementReviewOut(BaseModel):
    id: UUID
    requirement_id: UUID
    reviewed_by: UUID
    reviewed_at: datetime
    outcome: RequirementReviewOutcome
    comment: str | None = None


class RequirementDueForReviewOut(BaseModel):
    requirement_id: UUID
    project_id: UUID
    unique_code: str
    name: str
    review_date: date
    reviewer_id: UUID | None = None
