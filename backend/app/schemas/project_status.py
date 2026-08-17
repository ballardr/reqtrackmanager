"""
Module: schemas.project_status

Request/response models for org-definable project statuses
(`ProjectStatusDefinition`). Shares the rename/delete/reassign contract
described in `services.definitions`' module docstring with
`schemas.link_type` and `schemas.action_type`.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel


class ProjectStatusCreate(BaseModel):
    """Payload to create a new project status in an organisation."""

    name: str


class ProjectStatusUpdate(BaseModel):
    """Rename payload — see `services.definitions`' module docstring:
    renaming never disturbs any project currently on this status, since
    every reference points at the row's id, never its name."""

    name: str


class ProjectStatusOut(BaseModel):
    model_config = {"from_attributes": True}

    id: UUID
    organization_id: UUID
    name: str
    sort_order: int
