"""
Module: schemas.project

Request/response models for projects, stages, components, categories,
project groups, and project role assignments (C-G-04, C-G-07, C-G-08,
C-U-03, C-U-11).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, field_validator

from app.models.enums import ProjectRole, StageStatus

# Fixed, documented set of overridable terminology keys (C-C-03). Not a
# freeform key-value store — terminology only covers these nouns.
TERMINOLOGY_KEYS = {"project", "stage", "component", "category", "requirement", "change_request"}


class ProjectCreate(BaseModel):
    organization_id: UUID
    name: str
    summary: str = ""
    template_project_id: UUID | None = None  # C-E-05: create from an existing template project


class ProjectOut(BaseModel):
    model_config = {"from_attributes": True}

    id: UUID
    organization_id: UUID
    name: str
    summary: str
    created_at: datetime
    updated_at: datetime
    is_archived: bool = False
    is_template: bool = False
    allow_member_change_requests: bool = True
    terminology: dict[str, str] = {}


class ProjectUpdate(BaseModel):
    """Project settings update (name/summary, C-U-13 toggle, C-E-05 template flag)."""

    name: str | None = None
    summary: str | None = None
    allow_member_change_requests: bool | None = None
    is_template: bool | None = None


class TerminologyUpdate(BaseModel):
    """Per-project terminology overrides (C-C-03)."""

    terminology: dict[str, str]

    @field_validator("terminology")
    @classmethod
    def _validate_keys(cls, value: dict[str, str]) -> dict[str, str]:
        unknown = set(value) - TERMINOLOGY_KEYS
        if unknown:
            raise ValueError(f"Unknown terminology keys: {sorted(unknown)}. Allowed: {sorted(TERMINOLOGY_KEYS)}")
        return value


class ProjectListItemOut(ProjectOut):
    """Project list view row (U-E-03): includes stage and role context."""

    current_stage_name: str | None = None
    current_stage_status: StageStatus | None = None
    my_roles: list[ProjectRole] = []
    is_favorite: bool = False


class ProjectStageCreate(BaseModel):
    name: str


class ProjectStageOut(BaseModel):
    model_config = {"from_attributes": True}

    id: UUID
    project_id: UUID
    name: str
    status: StageStatus
    sort_order: int
    is_current: bool
    approved_at: datetime | None = None


class ComponentCreate(BaseModel):
    name: str
    prefix: str


class ComponentOut(BaseModel):
    model_config = {"from_attributes": True}

    id: UUID
    project_id: UUID
    name: str
    prefix: str
    sort_order: int


class CategoryCreate(BaseModel):
    name: str
    prefix: str


class CategoryOut(BaseModel):
    model_config = {"from_attributes": True}

    id: UUID
    project_id: UUID
    name: str
    prefix: str
    sort_order: int


class MoveDirection(BaseModel):
    direction: str  # "up" or "down"


class ProjectGroupCreate(BaseModel):
    name: str
    role: ProjectRole


class ProjectGroupMemberAdd(BaseModel):
    user_id: UUID | None = None
    org_group_id: UUID | None = None


class ProjectGroupOut(BaseModel):
    id: UUID
    name: str
    role: ProjectRole
    is_default: bool
    member_user_ids: list[UUID]
    member_org_group_ids: list[UUID]


class UserProjectRoleAssign(BaseModel):
    user_id: UUID
    role: ProjectRole


class ProjectMetricsOut(BaseModel):
    """Project overview dashboard metrics (U-P-05)."""

    requirement_count: int
    requirement_completed_percent: float
    change_requests_proposed: int
    change_requests_approved: int
    change_requests_rejected: int
