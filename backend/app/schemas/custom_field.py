"""Module: schemas.custom_field — request/response models for per-project
custom attribute definitions (Pelion v2, C-C-01, C-C-02)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel

from app.models.custom_field import CustomFieldEntityKind, CustomFieldType


class CustomFieldDefinitionCreate(BaseModel):
    entity_kind: CustomFieldEntityKind
    name: str
    field_type: CustomFieldType
    options: list[Any] | None = None
    required: bool = False


class CustomFieldDefinitionOut(BaseModel):
    model_config = {"from_attributes": True}

    id: UUID
    project_id: UUID
    entity_kind: CustomFieldEntityKind
    name: str
    field_type: CustomFieldType
    options: list[Any] | None
    required: bool
    sort_order: int
