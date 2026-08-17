"""
Module: schemas.action_type

Request/response models for project-scoped requirement-action type
definitions (`ActionTypeDefinition`). Shares the rename/delete/reassign
contract described in `services.definitions`' module docstring with
`schemas.project_status` and `schemas.link_type` — the only difference is
scope (project, not organisation), per the user's explicit scope call
(see `models/action_type.py`'s docstring).
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel


class ActionTypeCreate(BaseModel):
    name: str


class ActionTypeUpdate(BaseModel):
    """Rename payload — see `services.definitions`' module docstring:
    renaming never disturbs any action currently of this type, since every
    reference points at the row's id, never its name."""

    name: str


class ActionTypeOut(BaseModel):
    model_config = {"from_attributes": True}

    id: UUID
    project_id: UUID
    name: str
    sort_order: int
