"""
Module: schemas.baseline

Request/response models for a project's baselines (C-G-10): the list shows each baseline's kind, stage and how many
records of each type it captured; a module's own routes read the captured content.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.models.enums import BaselineKind


class BaselineOut(BaseModel):
    """One baseline of a project.

    Attributes:
        id: The baseline's id.
        kind: `stage` (written when a stage entered a locked phase) or `manual`.
        label: The baseline's name.
        stage_id: The stage, for a `stage` baseline.
        stage_name: The stage's name, for a `stage` baseline.
        component_id: Set for a component's own baseline.
        created_by: The person who took it.
        created_by_name: Their display name.
        created_at: When it was taken (UTC).
        item_counts: `{item type: number of records captured}`; `requirement` plus each module type.
    """

    id: UUID
    kind: BaselineKind
    label: str
    stage_id: UUID | None
    stage_name: str | None
    component_id: UUID | None
    created_by: UUID
    created_by_name: str | None
    created_at: datetime
    item_counts: dict[str, int]


class ManualBaselineCreate(BaseModel):
    """Body of a manual baseline request.

    Attributes:
        label: The baseline's name.
        item_types: The types to capture; omitted, every type the caller may snapshot.
    """

    label: str = Field(min_length=1, max_length=255)
    item_types: list[str] | None = None

    @field_validator("label")
    @classmethod
    def _label_not_blank(cls, value: str) -> str:
        """Rejects a label that is only whitespace and trims the rest."""
        value = value.strip()
        if not value:
            raise ValueError("label must not be blank.")
        return value
