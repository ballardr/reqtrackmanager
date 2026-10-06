"""
Module: schemas.link_type

Request/response models for org-definable, bidirectional requirement link
types (`RequirementLinkTypeDefinition`). Shares the rename/delete/reassign
contract described in `services.definitions`' module docstring with
`schemas.project_status` and `schemas.action_type`.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel

from app.models.enums import LinkFlow


class LinkTypeCreate(BaseModel):
    """Payload to create a new link type in an organisation. Both directional
    names are required up front — a link type with only one name defined
    would render blank/wrong when read from the other direction."""

    forward_name: str
    reverse_name: str
    flow: LinkFlow = LinkFlow.NONE


class LinkTypeUpdate(BaseModel):
    """Renames both directional names at once — see
    `services.definitions`' module docstring: renaming never disturbs any
    existing link using this type, since every reference points at the
    row's id, never its names. `flow` left out keeps the current direction."""

    forward_name: str
    reverse_name: str
    flow: LinkFlow | None = None


class LinkTypeOut(BaseModel):
    model_config = {"from_attributes": True}

    id: UUID
    organization_id: UUID
    forward_name: str
    reverse_name: str
    sort_order: int
    flow: LinkFlow
