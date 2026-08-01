"""
Module: schemas.change_request

Request/response models for the change request workflow (introduction,
C-G-03, C-G-12).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from app.models.enums import ChangeRequestKind, ChangeRequestStatus


class ChangeRequestCreate(BaseModel):
    kind: ChangeRequestKind
    requirement_id: UUID | None = None
    proposed_name: str
    proposed_reasoning: str = ""
    proposed_clarification: str = ""
    proposed_component_id: UUID | None = None
    proposed_category_id: UUID | None = None
    reason: str
    custom_fields: dict[str, Any] = {}
    creator_id: UUID | None = None  # PM-only override (C-A-12)


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
    reason: str
    custom_fields: dict[str, Any]
    submitted_at: datetime | None
    decided_at: datetime | None
    decided_by: UUID | None
    decision_note: str
    created_at: datetime


class ChangeRequestDecision(BaseModel):
    approve: bool
    note: str = ""
