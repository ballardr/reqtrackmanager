"""
Module: modules.stakeholders.schemas

Pydantic request/response schemas for the Stakeholders & Personas module's
org- and project-scoped routers (Phase 1.1: Persona, persona types, weight
overrides, comments).

`PersonaUpdate` is partial: only fields present in the request body change,
so a nullable field (weight, owner, champion, type) can be cleared by sending
an explicit `null`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.modules.stakeholders.enums import PersonaScope, PersonaStatus
from app.schemas.file import FileAssetOut

# A positive, finite importance weight (`inf` would poison a weighted roll-up).
Weight = Annotated[float, Field(gt=0, allow_inf_nan=False)]


class PersonaCreate(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    description: str = ""
    persona_type_id: UUID | None = None
    role_title: str = Field(default="", max_length=300)
    goals: str = ""
    needs: str = ""
    behaviours: str = ""
    context_environment: str = ""
    skills_proficiency: str = ""
    frequency_of_use: str = ""
    constraints: str = ""
    weight: Weight | None = None
    owner_id: UUID | None = None
    champion_id: UUID | None = None


class PersonaUpdate(BaseModel):
    """Partial update; see module docstring. `status` is not editable here —
    use the lifecycle endpoints."""

    name: str | None = Field(default=None, min_length=1, max_length=300)
    description: str | None = None
    persona_type_id: UUID | None = None
    role_title: str | None = Field(default=None, max_length=300)
    goals: str | None = None
    needs: str | None = None
    behaviours: str | None = None
    context_environment: str | None = None
    skills_proficiency: str | None = None
    frequency_of_use: str | None = None
    constraints: str | None = None
    weight: Weight | None = None
    owner_id: UUID | None = None
    champion_id: UUID | None = None
    change_note: str = ""


class PersonaOut(BaseModel):
    """A persona merged with its current version. `effective_weight` and
    `weight_override`/`weight_source` are populated only by the project router:
    the resolved weight for that project, the project's own override (if any),
    and the tier the resolved weight came from."""

    id: UUID
    scope: PersonaScope
    organization_id: UUID | None
    project_id: UUID | None
    creator_id: UUID
    is_archived: bool
    archived_at: datetime | None
    archived_by: UUID | None

    name: str
    description: str
    persona_type_id: UUID | None
    persona_type_name: str | None
    role_title: str
    goals: str
    needs: str
    behaviours: str
    context_environment: str
    skills_proficiency: str
    frequency_of_use: str
    constraints: str
    weight: float | None
    status: PersonaStatus
    owner_id: UUID | None
    champion_id: UUID | None
    version_number: int

    effective_weight: float | None = None
    weight_override: float | None = None
    weight_source: Literal["project", "ancestor_project", "persona", "none"] | None = None

    created_at: datetime
    updated_at: datetime


class PersonaVersionOut(BaseModel):
    """One historical snapshot."""

    model_config = {"from_attributes": True}

    id: UUID
    persona_id: UUID
    version_number: int
    valid_from: datetime
    valid_to: datetime | None
    name: str
    description: str
    org_type_id: UUID | None
    project_type_id: UUID | None
    role_title: str
    goals: str
    needs: str
    behaviours: str
    context_environment: str
    skills_proficiency: str
    frequency_of_use: str
    constraints: str
    weight: float | None
    status: PersonaStatus
    owner_id: UUID | None
    champion_id: UUID | None
    change_note: str
    created_by: UUID
    created_at: datetime


class PersonaTransitionRequest(BaseModel):
    comment: str | None = None


class PersonaWeightSet(BaseModel):
    weight: Weight


class PersonaCommentCreate(BaseModel):
    body: str = Field(min_length=1)


class PersonaCommentUpdate(BaseModel):
    body: str = Field(min_length=1)


class PersonaCommentOut(BaseModel):
    id: UUID
    persona_id: UUID
    author_id: UUID
    author_display_name: str
    body: str
    created_at: datetime
    edited_at: datetime | None = None
    attachments: list[FileAssetOut] = []


class PersonaTypeCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class PersonaTypeUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    is_active: bool | None = None


class PersonaTypeOut(BaseModel):
    """An org-scoped `PersonaTypeDefinition` row."""

    model_config = {"from_attributes": True}

    id: UUID
    organization_id: UUID
    name: str
    sort_order: int
    is_active: bool


class EffectiveTypeOut(BaseModel):
    """One row of a project's merged type list (`type_vocabulary.EffectiveType`)."""

    model_config = {"from_attributes": True}

    id: UUID
    name: str
    display_order: int
    is_enabled: bool
    source: str


class ProjectTypeCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    display_order: int | None = None


class ProjectTypeOverrideUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    display_order: int | None = None
    is_enabled: bool | None = None


class ProjectTypeOut(BaseModel):
    """A raw project type row (override or project-local)."""

    model_config = {"from_attributes": True}

    id: UUID
    project_id: UUID
    org_type_id: UUID | None
    name_override: str | None
    display_order_override: int | None
    is_enabled: bool
