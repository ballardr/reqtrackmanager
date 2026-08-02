"""
Module: schemas.change_request

Request/response models for the change request workflow (introduction,
C-G-03, C-G-12), plus review-stage tasks (C-R-02/04) and stakeholder voting
(C-R-03) added in Massif (v3).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from app.models.enums import ChangeRequestKind, ChangeRequestStatus, ChangeRequestVoteChoice, RequirementLevel


class ChangeRequestCreate(BaseModel):
    kind: ChangeRequestKind
    requirement_id: UUID | None = None
    proposed_name: str
    proposed_reasoning: str = ""
    proposed_clarification: str = ""
    proposed_component_id: UUID | None = None
    proposed_category_id: UUID | None = None
    proposed_target_stage_id: UUID | None = None
    proposed_level: RequirementLevel = RequirementLevel.REQUIREMENT
    reason: str
    custom_fields: dict[str, Any] = {}
    creator_id: UUID | None = None  # PM-only override (C-A-12)
    proposed_review_date: date | None = None  # C-R-06
    proposed_review_lead_days: int | None = None
    proposed_reviewer_id: UUID | None = None  # C-R-10


class ChangeRequestOut(BaseModel):
    id: UUID
    project_id: UUID
    requirement_id: UUID | None
    kind: ChangeRequestKind
    status: ChangeRequestStatus
    creator_id: UUID
    proposed_name: str
    proposed_reasoning: str
    proposed_clarification: str
    proposed_target_stage_id: UUID | None = None
    proposed_level: RequirementLevel = RequirementLevel.REQUIREMENT
    reason: str
    custom_fields: dict[str, Any]
    submitted_at: datetime | None
    decided_at: datetime | None
    decided_by: UUID | None
    decision_note: str
    created_at: datetime
    is_subscribed: bool = False
    # Derived list-view indicators (mock's card "badges"), computed at read time.
    comment_count: int = 0
    requires_approval: bool = False
    proposed_review_date: date | None = None
    proposed_review_lead_days: int | None = None
    proposed_reviewer_id: UUID | None = None


class ChangeRequestDecision(BaseModel):
    approve: bool
    note: str = ""


class ChangeRequestTaskCreate(BaseModel):
    description: str
    assignee_id: UUID | None = None
    due_date: date | None = None


class ChangeRequestTaskUpdate(BaseModel):
    description: str | None = None
    assignee_id: UUID | None = None
    due_date: date | None = None
    is_done: bool | None = None


class ChangeRequestTaskOut(BaseModel):
    id: UUID
    change_request_id: UUID
    description: str
    assignee_id: UUID | None = None
    due_date: date | None = None
    is_done: bool
    completed_at: datetime | None = None
    created_by: UUID
    created_at: datetime


class ChangeRequestVoteCreate(BaseModel):
    vote: ChangeRequestVoteChoice
    comment: str | None = None


class ChangeRequestVoteOut(BaseModel):
    model_config = {"from_attributes": True}

    id: UUID
    change_request_id: UUID
    user_id: UUID
    vote: ChangeRequestVoteChoice
    comment: str | None = None
    voted_at: datetime


class ChangeRequestVoteTallyOut(BaseModel):
    votes: list[ChangeRequestVoteOut]
    approve_count: int
    reject_count: int
